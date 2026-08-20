#!/usr/bin/env python3
"""benchmark.py — compare detection quality across footage and inference sizes.

Detection quality is not a property of the model alone. Running the same weights
over the same match at three different (source resolution, inference size) pairs
moved the ball-detection rate from 2.2% to 33.2% — a fifteenfold swing with no
change to the model, the footage, or the thresholds. A ball is a handful of
pixels; shrink the frame before inference and there is nothing left to detect.
That result is only trustworthy because all three arms saw the identical segment
of the identical match, which is what this script exists to guarantee.

An arm is a (video, inference size) pair. Everything else — model, device,
stride, confidence, segment — is shared across arms, so any difference in the
output table is caused by the thing being varied.

    python scripts/benchmark.py \\
        360p=/footage/tottenham_360p.mp4@960 \\
        1080p=/footage/tottenham_1080p.mp4@960 \\
        1080p-hi=/footage/tottenham_1080p.mp4@1920 \\
        --at 600 --seconds 600 --out benchmarks/imgsz.json

On timing
---------
Two earlier runs of this comparison were destroyed by the Mac going to sleep
mid-benchmark; one reported 26120 seconds of wall clock for a few minutes of
work, and the number was reported as if it were real. Both defences are wired in
here:

  * The process re-executes itself under ``caffeinate -i`` on macOS, so the
    machine does not idle-sleep during a run. ``--no-caffeinate`` opts out.
  * ``time.monotonic`` stops while the machine is suspended and ``time.time``
    does not, so the gap between the two *is* the time spent asleep. Wall clock
    is reported from the monotonic clock and any suspension is reported as its
    own figure rather than silently folded into the result.

Writes only to ``--out`` and the per-arm stats files beside it. The live runner
defaults its output to match_stats.json / match_data.json; nothing here may go
near those, and refuse_protected_output() enforces it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

# Make the repo-root modules importable no matter where this is launched from.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Files that belong to a real match, not to a benchmark. A benchmark writes a
# throwaway document per arm; if one of these ever appeared as an output path it
# would overwrite the user's live match with test data, silently and
# irrecoverably. Cheaper to refuse than to explain afterwards.
PROTECTED_OUTPUTS = ("match_stats.json", "match_data.json", "control.json",
                     "recorder.json")

# Set on the re-executed child so the caffeinate wrapper is applied once, not
# recursively forever.
CAFFEINATED_ENV = "KICKOFF_BENCH_CAFFEINATED"

# Under a couple of seconds, a calendar/monotonic divergence is an NTP step or
# clock rounding, not the lid being closed. Above it, the machine slept.
SUSPEND_TOLERANCE_SECONDS = 5.0


def refuse_protected_output(path: str) -> str:
    """Return ``path``, or raise if it would clobber real match data."""
    if os.path.basename(os.path.abspath(path)) in PROTECTED_OUTPUTS:
        raise ValueError(
            f"{path!r} is live match data; a benchmark must not write it. "
            f"Choose a path under --out-dir instead."
        )
    return path


# --------------------------------------------------------------------------- #
# Arms
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Arm:
    """One leg of the comparison: a video analysed at one inference size."""

    label: str
    video: str
    imgsz: int


def parse_arm(spec: str) -> Arm:
    """Parse ``[label=]video@imgsz``.

    Split from the right on ``@`` so a path or URL containing one still parses;
    the inference size is always the last field. The label is optional and
    defaults to the filename plus the size, which is enough to read a table by.
    """
    label = ""
    if "=" in spec and spec.index("=") < spec.rfind("@"):
        label, spec = spec.split("=", 1)
    if "@" not in spec:
        raise ValueError(f"arm {spec!r} needs an inference size, as video@imgsz")
    video, size = spec.rsplit("@", 1)
    try:
        imgsz = int(size)
    except ValueError:
        raise ValueError(f"arm {spec!r}: {size!r} is not an inference size") from None
    if not video:
        raise ValueError(f"arm {spec!r} has no video")
    label = label or f"{os.path.basename(video) or video}@{imgsz}"
    return Arm(label=label, video=video, imgsz=imgsz)


# --------------------------------------------------------------------------- #
# Timing
# --------------------------------------------------------------------------- #
class Stopwatch:
    """Wall clock that can tell work from sleep.

    ``time.monotonic`` is backed by a clock that does not advance while the
    machine is suspended, while ``time.time`` keeps counting through it. Reading
    both and differencing them is the cheapest reliable way to notice that a
    benchmark result covers a night on the desk rather than ten minutes of
    inference.

    CPU time is carried alongside as a second opinion: a run whose CPU time is a
    tiny fraction of its wall clock either slept or spent the time blocked, and
    either way the throughput figure is not measuring what it claims to. It is
    not on its own proof of a problem — GPU inference genuinely idles the CPU —
    so it is reported, not asserted on.
    """

    def __init__(self) -> None:
        self._mono0 = time.monotonic()
        self._cal0 = time.time()
        self._cpu0 = time.process_time()
        self._stopped: Optional[tuple] = None

    def stop(self) -> "Stopwatch":
        self._stopped = (time.monotonic(), time.time(), time.process_time())
        return self

    def _now(self) -> tuple:
        return self._stopped or (time.monotonic(), time.time(), time.process_time())

    @property
    def wall(self) -> float:
        """Seconds of real elapsed time, excluding machine suspension."""
        return self._now()[0] - self._mono0

    @property
    def calendar(self) -> float:
        """Seconds by the wall calendar, including any suspension."""
        return self._now()[1] - self._cal0

    @property
    def cpu(self) -> float:
        return self._now()[2] - self._cpu0

    @property
    def suspended(self) -> float:
        """Seconds the machine appears to have been asleep. 0 when it was not."""
        gap = self.calendar - self.wall
        return gap if gap > SUSPEND_TOLERANCE_SECONDS else 0.0

    def to_dict(self) -> dict:
        return {
            "wall_seconds": round(self.wall, 2),
            "calendar_seconds": round(self.calendar, 2),
            "cpu_seconds": round(self.cpu, 2),
            "suspended_seconds": round(self.suspended, 2),
        }


def caffeinate_command(argv: Sequence[str]) -> List[str]:
    """The command that re-runs this benchmark with idle sleep held off.

    ``-i`` blocks idle sleep only; closing the lid still sleeps the machine, and
    nothing in userspace can prevent that. The suspension detector in Stopwatch
    is the backstop for exactly that case.
    """
    return ["caffeinate", "-i", sys.executable, *argv]


def maybe_reexec_under_caffeinate(argv: Sequence[str]) -> None:
    """On macOS, restart this process under caffeinate. Returns if not needed."""
    if sys.platform != "darwin" or os.environ.get(CAFFEINATED_ENV):
        return
    if not shutil.which("caffeinate"):
        return
    os.environ[CAFFEINATED_ENV] = "1"
    cmd = caffeinate_command(argv)
    print(f"[bench] holding off idle sleep: {' '.join(cmd)}", flush=True)
    os.execvp(cmd[0], cmd)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
class ArmMetrics:
    """Accumulates detection quality over the frames one arm produced.

    Deliberately duck-typed over :class:`vision.schema.FrameRecord` (it reads
    ``record.ball.x`` and ``record.players[].id``) so the arithmetic can be
    tested without standing up YOLO.
    """

    def __init__(self) -> None:
        self.frames = 0
        self.ball_frames = 0
        self.blank_frames = 0
        self.player_counts: List[int] = []
        self.track_ids = set()

    def observe(self, record) -> None:
        self.frames += 1
        players = list(getattr(record, "players", []) or [])
        # Coordinates are only present on frames where the ball was actually
        # detected; ball.status is inferred and persists across misses, so it
        # would report a far rosier rate than reality. live_vision counts it the
        # same way, which is what makes the two figures comparable.
        ball = getattr(record, "ball", None)
        ball_seen = ball is not None and getattr(ball, "x", None) is not None
        if ball_seen:
            self.ball_frames += 1
        if not players and not ball_seen:
            self.blank_frames += 1
        self.player_counts.append(len(players))
        for player in players:
            self.track_ids.add(player.id)

    def summary(self) -> dict:
        frames = self.frames
        return {
            "frames": frames,
            "ball_detection_rate": (self.ball_frames / frames) if frames else 0.0,
            "players_per_frame": (statistics.mean(self.player_counts)
                                  if self.player_counts else 0.0),
            "blank_frame_rate": (self.blank_frames / frames) if frames else 0.0,
            # An upper bound on the number of players seen, not a count of them:
            # a token changes when a jersey number finally binds, and identity
            # churn mints new ones. Read it as tracking stability — for the same
            # footage and segment, fewer ids is a steadier arm.
            "distinct_track_ids": len(self.track_ids),
        }


@dataclass
class ArmResult:
    arm: Arm
    metrics: dict = field(default_factory=dict)
    timing: dict = field(default_factory=dict)
    source_width: int = 0
    source_height: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.arm.label,
            "video": self.arm.video,
            "imgsz": self.arm.imgsz,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "error": self.error,
            **self.metrics,
            **self.timing,
        }


# --------------------------------------------------------------------------- #
# Running an arm
# --------------------------------------------------------------------------- #
def build_config(arm: Arm, args, stats_path: str):
    """The pipeline config for one arm. Everything but imgsz is shared.

    OCR is off by default. It is a large, variable slice of the wall clock and
    it reads numbers off players the detector already found, so leaving it on
    would blur the throughput comparison without changing what is being measured.
    """
    from vision.config import PipelineConfig

    return PipelineConfig(
        model_path=args.model,
        device=args.device,
        detection_imgsz=arm.imgsz,
        detection_conf=args.conf,
        frame_stride=args.stride,
        max_seconds=args.seconds,
        ocr_enabled=bool(args.ocr),
        output_path=refuse_protected_output(stats_path),
    )


def _seek(analyzer, seconds: float) -> bool:
    """Move an opened analyzer's capture to ``seconds``. True if it took.

    Reaching into the analyzer's capture is not pretty, but the alternative is
    decoding and discarding ten minutes of video per arm. Arms must start at the
    same point in the match to be comparable, and the opening minutes of a match
    file are usually the camera being levelled over an empty pitch — the least
    representative footage in the whole recording.
    """
    cap = getattr(analyzer, "_cap", None)
    if cap is None or seconds <= 0:
        return False
    import cv2

    return bool(cap.set(cv2.CAP_PROP_POS_MSEC, float(seconds) * 1000.0))


def default_analyzer(config):
    from vision.pipeline import MatchAnalyzer

    return MatchAnalyzer(config)


def run_arm(arm: Arm, args, analyzer_factory: Callable = None,
            stats_path: str = "") -> ArmResult:
    """Analyse one arm's segment and return its measured quality."""
    analyzer_factory = analyzer_factory or default_analyzer
    stats_path = stats_path or os.path.join(args.out_dir, f"{_slug(arm.label)}.json")
    result = ArmResult(arm=arm)

    config = build_config(arm, args, stats_path)
    analyzer = analyzer_factory(config)
    metrics = ArmMetrics()
    watch = Stopwatch()
    try:
        analyzer.open(arm.video)
        result.source_width = int(getattr(analyzer, "_frame_w", 0) or 0)
        result.source_height = int(getattr(analyzer, "_frame_h", 0) or 0)
        _seek(analyzer, args.at)
        while True:
            out = analyzer.step()
            if out is None:
                break
            metrics.observe(out[3])
            if args.max_frames and metrics.frames >= args.max_frames:
                break
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        watch.stop()
        try:
            # save=False: the document is beside the point here, and a save
            # would write the pipeline's own version over a path we control.
            analyzer.close(save=False)
        except Exception:
            pass

    result.metrics = metrics.summary()
    result.timing = watch.to_dict()
    frames = result.metrics["frames"]
    result.timing["frames_per_second"] = (
        round(frames / watch.wall, 2) if watch.wall > 0 else 0.0)
    return result


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in text).strip("-")


def run_benchmark(arms: Sequence[Arm], args,
                  analyzer_factory: Callable = None) -> dict:
    """Run every arm in order and assemble the report document."""
    results = []
    for index, arm in enumerate(arms, 1):
        print(f"[bench] arm {index}/{len(arms)}: {arm.label} "
              f"({arm.video}, imgsz {arm.imgsz})", flush=True)
        result = run_arm(arm, args, analyzer_factory=analyzer_factory)
        results.append(result)
        if result.error:
            print(f"[bench]   failed: {result.error}", flush=True)
        else:
            print(f"[bench]   {result.metrics['frames']} frames, ball "
                  f"{result.metrics['ball_detection_rate']:.1%}, "
                  f"{result.timing['wall_seconds']:.0f}s", flush=True)
    return {
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": args.model,
        "device": args.device,
        "stride": args.stride,
        "conf": args.conf,
        "at": args.at,
        "seconds": args.seconds,
        "ocr": bool(args.ocr),
        "arms": [r.to_dict() for r in results],
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
_TABLE_HEADER = (f"{'Arm':<22}{'imgsz':>7}{'Frames':>8}{'Ball':>8}"
                 f"{'Players':>9}{'Blank':>8}{'Ids':>6}{'Wall':>9}{'fps':>7}")


def format_table(report: dict) -> str:
    """The results table. One row per arm, in the order they ran."""
    lines = [_TABLE_HEADER, "-" * len(_TABLE_HEADER)]
    for arm in report.get("arms", []):
        if arm.get("error"):
            lines.append(f"{arm['label'][:21]:<22}{arm['imgsz']:>7}"
                         f"  failed: {arm['error']}")
            continue
        lines.append(
            f"{arm['label'][:21]:<22}{arm['imgsz']:>7}{arm['frames']:>8}"
            f"{arm['ball_detection_rate']:>8.1%}"
            f"{arm['players_per_frame']:>9.1f}"
            f"{arm['blank_frame_rate']:>8.1%}"
            f"{arm['distinct_track_ids']:>6}"
            f"{arm['wall_seconds']:>8.0f}s"
            f"{arm['frames_per_second']:>7.1f}"
        )
    lines.append("")
    lines.append(f"model={report.get('model')} device={report.get('device')} "
                 f"stride={report.get('stride')} conf={report.get('conf')} "
                 f"segment={report.get('at')}s+{report.get('seconds')}s")

    # A suspended machine invalidates every timing column, so say so loudly
    # rather than letting a plausible-looking number stand.
    slept = [a for a in report.get("arms", []) if a.get("suspended_seconds")]
    if slept:
        lines.append("")
        lines.append("WARNING: the machine slept during this run; timings below "
                     "are not comparable. Re-run under 'caffeinate -i'.")
        for arm in slept:
            lines.append(f"  {arm['label']}: asleep for "
                         f"{arm['suspended_seconds']:.0f}s of "
                         f"{arm['calendar_seconds']:.0f}s elapsed")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="benchmark",
        description="N-arm detection-quality comparison. An arm is "
                    "[label=]video@imgsz.")
    p.add_argument("arms", nargs="+", help="Arms: [label=]video@imgsz")
    p.add_argument("--model", default="soccer_yolov8m_v1.pt", help="YOLO weights.")
    p.add_argument("--device", default="mps", help="'mps', 'cpu', '0', 'cuda'.")
    p.add_argument("--stride", type=int, default=6,
                   help="Process 1 of every N frames, as the live runner does.")
    p.add_argument("--conf", type=float, default=0.25, help="Detection confidence.")
    p.add_argument("--at", type=float, default=0.0,
                   help="Seconds into each video to start. Arms must cover the "
                        "same segment of the same match to be comparable.")
    p.add_argument("--seconds", type=float, default=600.0,
                   help="Seconds of footage per arm (default 600).")
    p.add_argument("--max-frames", type=int, default=0,
                   help="Hard cap on processed frames per arm (0 = no cap).")
    p.add_argument("--ocr", action="store_true",
                   help="Leave jersey OCR on. Off by default: it costs a large "
                        "and variable share of the wall clock without changing "
                        "what is being detected.")
    p.add_argument("--out-dir", default="benchmarks",
                   help="Where the report and per-arm stats are written.")
    p.add_argument("--out", default="",
                   help="Report path (default: <out-dir>/benchmark-<stamp>.json).")
    p.add_argument("--no-caffeinate", action="store_true",
                   help="Do not re-exec under caffeinate. The machine may then "
                        "idle-sleep mid-run and ruin the timings.")
    args = p.parse_args(argv)

    try:
        arms = [parse_arm(spec) for spec in args.arms]
    except ValueError as exc:
        p.error(str(exc))

    out = args.out or os.path.join(
        args.out_dir, f"benchmark-{time.strftime('%Y%m%d-%H%M%S')}.json")
    try:
        refuse_protected_output(out)
    except ValueError as exc:
        p.error(str(exc))

    # Everything is validated before the re-exec, so a mistyped invocation fails
    # here rather than in a child process the caller cannot see.
    if not args.no_caffeinate:
        maybe_reexec_under_caffeinate(sys.argv)

    os.makedirs(args.out_dir, exist_ok=True)

    report = run_benchmark(arms, args)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print()
    print(format_table(report))
    print()
    print(f"Report: {out}")
    return 0 if all(not a.get("error") for a in report["arms"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
