#!/usr/bin/env python3
"""footage_probe.py — measure whether a camera actually holds still.

Everything spatial the Eye produces rests on the camera being fixed. A pitch
calibration is one homography, and a homography is only valid while the view
does not change; the moment the camera follows play the mapping goes stale and
every position it produces is wrong in a way nothing downstream can detect (see
quality.assess, which can only warn about it after the fact). So "does this
camera move?" is not a detail — it decides whether a match's positions,
distances and zones mean anything at all.

The trap is that footage titles lie. In the verified corpus two clips sold as
"tactical camera" pan by 3-4 px a second, while one titled "Panorama" turned out
to be the most static footage found. Camera motion is measured here, never
inferred from a title. The corpus and the standing rule live in docs/FOOTAGE.md.

Method
------
Sample one frame per second, downscale each to 320x180 grayscale float32, and
run ``cv2.phaseCorrelate`` on consecutive samples. Phase correlation locates the
peak of the cross-power spectrum of the two frames, which gives the global
translation between them to sub-pixel precision, plus a response saying how
sharp that peak was. Two properties are what make it the right tool here:

  * It is a whole-frame measurement, so a dozen players running does not move
    the estimate — they are a small fraction of the pixels. A camera pan moves
    every pixel, so it does.
  * The response doubles as a scene-change detector. Frames from two different
    cameras share no structure, so the peak collapses instead of shifting.

One frame per second is deliberate. Consecutive video frames of a slow pan
differ by a fraction of a pixel, which is below the noise floor; a one-second
baseline turns the same pan into a measurable displacement while staying short
enough that a real pan has not wrapped around to nothing.

    python scripts/footage_probe.py match.mp4 --at 600 --for 120
    python scripts/footage_probe.py a.mp4 b.mp4 --detail
    python scripts/footage_probe.py "https://www.youtube.com/watch?v=..." --at 1200

Read-only. This writes nothing but its report.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from dataclasses import dataclass, field
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple

import numpy as np

# Make the repo-root modules importable no matter where this is launched from.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# --------------------------------------------------------------------------- #
# The probe space.
#
# Every shift below is measured in these pixels, not source pixels. Downscaling
# is not only about speed: it low-pass filters the frame, which is what stops
# compression noise and grass texture from producing a spurious peak. 320x180
# keeps enough structure (lines, boxes, stands) for the correlation to lock on.
#
# The consequence to remember when reading a number: 1 probe pixel is 6 source
# pixels at 1920x1080 and 12 at 3840x2160.
# --------------------------------------------------------------------------- #
PROBE_WIDTH = 320
PROBE_HEIGHT = 180

# --------------------------------------------------------------------------- #
# Thresholds, and why they are where they are.
#
# FIXED_PX — phase correlation is a sub-pixel estimator; even between two
# genuinely identical scenes, encoder noise shifts the fitted peak by a few
# hundredths of a pixel. 0.15 is the floor below which "it moved" is
# indistinguishable from "the estimator jittered", so anything under it is a
# camera that is bolted down. The corpus's most static clip measured 0.09.
#
# NEAR_FIXED_PX — 1 probe pixel per second is ~6 pixels per second at 1080p:
# mount flex in wind, or a tripod settling. It is not a camera following play.
# The separation in practice is not marginal, which is the real justification —
# every fixed-mount clip measured came in under 0.7, every auto-following one
# over 2.9. One homography survives the first band; nothing survives the second.
#
# CUT_RESPONSE — the response is the normalised height of the correlation peak.
# Consecutive samples of the same scene score near 1.0 even while panning
# (measured on synthetic translations: 1.000). Two unrelated frames score under
# 0.01. 0.05 sits in the empty middle of that gap.
#
# CUT_SHIFT_PX — the other face of a cut. When two shots happen to share
# structure (same stadium, same crowd) the peak does not collapse; it lands
# somewhere arbitrary instead. 40 px is a quarter of the probe frame — no camera
# that is still usable pans that far in one second.
#
# CUT_RATE_BROADCAST — one discontinuity in a two-minute probe is a dropped
# segment or a camera flash, not an editor. A directed broadcast cuts every few
# seconds. More than one cut per minute separates the two without a debate.
# --------------------------------------------------------------------------- #
FIXED_PX = 0.15
NEAR_FIXED_PX = 1.0
CUT_RESPONSE = 0.05
CUT_SHIFT_PX = 40.0
CUT_RATE_BROADCAST = 1.0

FIXED = "fixed"
NEAR_FIXED = "near-fixed"
PANS = "pans"
CUTS = "cuts"
UNKNOWN = "unknown"

VERDICT_NOTE = {
    FIXED: "bolted down; one calibration holds for the whole match",
    NEAR_FIXED: "drifts under a pixel a second; one calibration still holds",
    PANS: "the camera follows play; a fixed homography goes stale",
    CUTS: "cut broadcast, not single-camera footage; unusable for tracking",
    UNKNOWN: "not enough samples to say",
}

# A verdict is "usable" when a single pitch calibration can be trusted for the
# whole match. That is the only question this tool exists to answer.
USABLE_VERDICTS = (FIXED, NEAR_FIXED)


@dataclass
class Shift:
    """One consecutive-sample comparison."""

    t: float           # seconds into the source, at the later of the two samples
    dx: float          # translation of the *content*, probe pixels
    dy: float
    magnitude: float
    response: float
    cut: bool = False


@dataclass
class ProbeResult:
    """What a single source measured. Serialises straight to JSON."""

    source: str
    label: str
    samples: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    at: float = 0.0
    duration: float = 0.0
    seek_ok: bool = True
    verdict: str = UNKNOWN
    median_shift: float = 0.0
    p90_shift: float = 0.0
    max_shift: float = 0.0
    median_response: float = 0.0
    cuts: List[float] = field(default_factory=list)
    shifts: List[Shift] = field(default_factory=list)
    error: str = ""

    @property
    def usable(self) -> bool:
        return self.verdict in USABLE_VERDICTS

    @property
    def median_shift_source_px(self) -> float:
        """The same median expressed in the source's own pixels.

        Uses the width ratio. Downscaling to a fixed 320x180 squashes a source
        whose aspect ratio is not 16:9 differently in x and y, so this is an
        approximation for anything but 16:9 — which all match footage here is.
        """
        if not self.width:
            return 0.0
        return self.median_shift * (self.width / float(PROBE_WIDTH))

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "label": self.label,
            "samples": self.samples,
            "width": self.width,
            "height": self.height,
            "fps": round(self.fps, 3),
            "at": self.at,
            "duration": self.duration,
            "seek_ok": self.seek_ok,
            "verdict": self.verdict,
            "note": VERDICT_NOTE[self.verdict],
            "usable": self.usable,
            "median_shift_px": round(self.median_shift, 3),
            "median_shift_source_px": round(self.median_shift_source_px, 2),
            "p90_shift_px": round(self.p90_shift, 3),
            "max_shift_px": round(self.max_shift, 3),
            "median_response": round(self.median_response, 3),
            "cuts": [round(t, 1) for t in self.cuts],
            "error": self.error,
        }


# --------------------------------------------------------------------------- #
# Measurement
# --------------------------------------------------------------------------- #
def downscale(frame: np.ndarray) -> np.ndarray:
    """A BGR frame as a 320x180 grayscale float32 array.

    float32 because cv2.phaseCorrelate refuses integer input: the DFT it runs
    needs a floating-point array, and converting here keeps callers honest.
    """
    import cv2

    if frame.ndim == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(frame, (PROBE_WIDTH, PROBE_HEIGHT),
                       interpolation=cv2.INTER_AREA)
    return small.astype(np.float32)


def compare(previous: np.ndarray, current: np.ndarray, t: float) -> Shift:
    """Global translation between two probe frames, plus a cut flag.

    ``cv2.phaseCorrelate(a, b)`` returns the displacement of the content from
    ``a`` to ``b``: content that moved 3 px right returns dx=+3. Camera motion is
    the opposite sign, but only the magnitude matters here, so the raw content
    translation is reported rather than silently negated.

    No Hanning window is applied. One would suppress the frame-edge
    discontinuity the DFT sees, but the corpus in docs/FOOTAGE.md was measured
    without it, and changing the estimator would quietly invalidate every number
    recorded there.
    """
    import cv2

    (dx, dy), response = cv2.phaseCorrelate(previous, current)
    magnitude = float(np.hypot(dx, dy))
    cut = response < CUT_RESPONSE or magnitude > CUT_SHIFT_PX
    return Shift(t=t, dx=float(dx), dy=float(dy), magnitude=magnitude,
                 response=float(response), cut=cut)


def measure(samples: Iterable[Tuple[float, np.ndarray]]) -> List[Shift]:
    """Compare every consecutive pair of probe frames."""
    shifts: List[Shift] = []
    previous: Optional[np.ndarray] = None
    for t, frame in samples:
        if previous is not None:
            shifts.append(compare(previous, frame, t))
        previous = frame
    return shifts


def _percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile.

    Not worth pulling in numpy's interpolation rules for a handful of values,
    and nearest-rank always returns a figure that was actually measured.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return float(ordered[index])


def classify(shifts: Sequence[Shift], duration: float = 0.0) -> dict:
    """Turn a list of comparisons into a verdict.

    Cuts are excluded from the shift statistics. A cut is not camera motion, and
    including one would put a 6 px jump into a figure meant to describe a camera
    that never moved — the median would survive a few, but p90 and max would not,
    and those are what expose a camera that only pans when play switches ends.
    """
    cuts = [s.t for s in shifts if s.cut]
    clean = [s for s in shifts if not s.cut]
    magnitudes = [s.magnitude for s in clean]
    responses = [s.response for s in clean]

    # Cut rate is per minute of probed footage. Fall back to the comparison
    # count when the caller did not say how long the probe was, which is right
    # at the default of one sample a second.
    minutes = (duration / 60.0) if duration > 0 else (len(shifts) / 60.0)
    cut_rate = (len(cuts) / minutes) if minutes > 0 else 0.0

    if not magnitudes:
        verdict = CUTS if cuts else UNKNOWN
    elif cut_rate > CUT_RATE_BROADCAST:
        verdict = CUTS
    else:
        median = statistics.median(magnitudes)
        verdict = (FIXED if median < FIXED_PX
                   else NEAR_FIXED if median < NEAR_FIXED_PX
                   else PANS)

    return {
        "verdict": verdict,
        "median_shift": statistics.median(magnitudes) if magnitudes else 0.0,
        "p90_shift": _percentile(magnitudes, 0.9),
        "max_shift": max(magnitudes) if magnitudes else 0.0,
        "median_response": statistics.median(responses) if responses else 0.0,
        "cuts": cuts,
        "cut_rate_per_minute": cut_rate,
    }


# --------------------------------------------------------------------------- #
# Capture
# --------------------------------------------------------------------------- #
def iter_samples(cap, at: float, duration: float,
                 per_second: float) -> Iterator[Tuple[float, np.ndarray]]:
    """Yield ``(seconds, probe frame)`` at ``per_second`` samples a second.

    Frames between samples are grabbed but never decoded into an array —
    ``grab()`` skips the colour conversion, which is most of the cost of reading
    a 4K frame and is pure waste for 29 of every 30 frames.
    """
    import cv2

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 30.0
    step = max(1, int(round(fps / max(0.01, per_second))))
    wanted = max(2, int(round(duration * per_second)))

    taken = 0
    while taken < wanted:
        ok, frame = cap.read()
        if not ok or frame is None:
            return
        # Prefer the container's own clock; a stream that reports nothing gets
        # the nominal sample time instead.
        pos = float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
        t = pos if pos > 0 else at + taken / per_second
        yield t, downscale(frame)
        taken += 1
        for _ in range(step - 1):
            if not cap.grab():
                return


def probe(source, at: float = 0.0, duration: float = 60.0,
          per_second: float = 1.0, label: str = "") -> ProbeResult:
    """Measure one source end to end."""
    import cv2

    from vision.sources import SourceResolutionError, resolve_video_source

    result = ProbeResult(source=str(source), label=label or default_label(source),
                         at=at, duration=duration)
    try:
        resolved = resolve_video_source(source)
    except SourceResolutionError as exc:
        result.error = str(exc)
        return result

    cap = cv2.VideoCapture(resolved.capture_source)
    try:
        if not cap.isOpened():
            result.error = "could not open the source"
            return result
        result.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        result.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        result.fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)

        if at > 0:
            # A live stream has nothing to seek within, and the first minute of
            # a recording is usually the camera being levelled over an empty
            # pitch — the worst possible sample of how it behaves during play.
            result.seek_ok = bool(cap.set(cv2.CAP_PROP_POS_MSEC, at * 1000.0))

        shifts = measure(iter_samples(cap, at, duration, per_second))
    finally:
        cap.release()

    result.shifts = shifts
    result.samples = len(shifts) + 1 if shifts else 0
    summary = classify(shifts, duration=duration)
    result.verdict = summary["verdict"]
    result.median_shift = summary["median_shift"]
    result.p90_shift = summary["p90_shift"]
    result.max_shift = summary["max_shift"]
    result.median_response = summary["median_response"]
    result.cuts = summary["cuts"]
    if not shifts:
        result.error = result.error or "no frames decoded"
    return result


def default_label(source) -> str:
    """A short name for the table: a filename, or a YouTube id for a URL."""
    text = str(source)
    if "youtube.com" in text or "youtu.be" in text:
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(text)
        ident = parse_qs(parsed.query).get("v", [""])[0]
        return ident or parsed.path.strip("/") or text
    return os.path.basename(text.rstrip("/")) or text


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
_SUMMARY_HEADER = (f"{'Source':<28}{'Samples':>8}{'Median':>9}{'p90':>8}"
                   f"{'Max':>8}{'Resp':>7}{'Cuts':>6}  Verdict")


def format_summary(results: Sequence[ProbeResult]) -> str:
    """One row per source. Shifts are probe pixels (320x180)."""
    lines = [_SUMMARY_HEADER, "-" * (len(_SUMMARY_HEADER) + 12)]
    for r in results:
        label = r.label[:27]
        if r.error and not r.samples:
            lines.append(f"{label:<28}{'-':>8}{'-':>9}{'-':>8}{'-':>8}"
                         f"{'-':>7}{'-':>6}  error: {r.error}")
            continue
        lines.append(
            f"{label:<28}{r.samples:>8}{r.median_shift:>9.2f}{r.p90_shift:>8.2f}"
            f"{r.max_shift:>8.2f}{r.median_response:>7.2f}{len(r.cuts):>6}"
            f"  {r.verdict} - {VERDICT_NOTE[r.verdict]}"
        )
    lines.append("")
    lines.append(f"Shifts are pixels in the {PROBE_WIDTH}x{PROBE_HEIGHT} probe "
                 f"frame. Fixed < {FIXED_PX}, near-fixed < {NEAR_FIXED_PX}.")
    for r in results:
        if r.width and r.samples:
            lines.append(f"  {r.label[:27]}: {r.width}x{r.height}, median "
                         f"{r.median_shift_source_px:.2f} px at source scale")
    return "\n".join(lines)


def format_detail(result: ProbeResult) -> str:
    """The per-sample table the verdict was computed from."""
    lines = [
        f"{result.label} ({result.width}x{result.height} @ "
        f"{result.fps:.0f}fps), {result.samples} samples from "
        f"{result.at:.0f}s over {result.duration:.0f}s",
    ]
    if not result.seek_ok:
        lines.append("  seek was refused; samples start wherever the source did")
    lines.append(f"  {'t (s)':>9}{'dx':>8}{'dy':>8}{'shift':>8}{'resp':>7}  flag")
    for s in result.shifts:
        flag = "CUT" if s.cut else ""
        lines.append(f"  {s.t:>9.1f}{s.dx:>8.2f}{s.dy:>8.2f}"
                     f"{s.magnitude:>8.2f}{s.response:>7.2f}  {flag}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="footage_probe",
        description="Measure whether a camera is fixed. Never trust the title.")
    p.add_argument("sources", nargs="+",
                   help="Video files, stream URLs, or YouTube watch URLs.")
    p.add_argument("--at", type=float, default=0.0,
                   help="Seconds to seek to before probing. Aim at settled "
                        "play; the opening minute is usually an empty pitch.")
    p.add_argument("--for", dest="duration", type=float, default=60.0,
                   help="Seconds of footage to probe (default 60).")
    p.add_argument("--per-second", type=float, default=1.0,
                   help="Samples per second (default 1). Lower it only if a "
                        "pan is so slow a one-second baseline cannot see it.")
    p.add_argument("--detail", action="store_true",
                   help="Also print the per-sample table for each source.")
    p.add_argument("--json", action="store_true",
                   help="Print machine-readable JSON instead of the tables.")
    args = p.parse_args(argv)

    results = [probe(s, at=args.at, duration=args.duration,
                     per_second=args.per_second) for s in args.sources]

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        if args.detail:
            for r in results:
                print(format_detail(r))
                print()
        print(format_summary(results))

    # Non-zero only when nothing was measured, so a caller can tell a failed
    # probe from a verdict of "pans" — which is a successful measurement of
    # unusable footage.
    return 0 if any(r.samples for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
