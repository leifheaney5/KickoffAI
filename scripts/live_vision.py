#!/usr/bin/env python3
"""live_vision.py — run the vision pipeline (the Eye) as a standalone, persistent
background process, decoupled from the Streamlit UI.

Unlike the Video Analysis page (whose stepping loop only runs while that page is
the active script), this keeps capturing the whole match no matter what you click
in the app. It checkpoints periodically so the app sees live results:

  * match_stats.json  — the full vision document (overwritten each checkpoint)
  * match_data.json   — vision passes bridged into the dashboard event log

Run it:

    .venv/bin/python scripts/live_vision.py \
        --video "https://www.youtube.com/watch?v=VjsRuzSu0qU" \
        --model soccer_yolov8m_v1.pt --device mps

Stop it cleanly with Ctrl-C (or `kill <pid>`); it writes a final checkpoint and
removes its PID file on exit.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

# Make the repo-root modules importable no matter where this is launched from.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from vision import MatchAnalyzer, PipelineConfig  # noqa: E402
from vision import bridge as vbridge  # noqa: E402
from vision.runtime import live_config  # noqa: E402
from vision.schema import MatchStats  # noqa: E402

_STOP = False


def _request_stop(signum, frame):  # noqa: ARG001
    global _STOP
    _STOP = True


def write_snapshot(path: str, frame, detections, record) -> None:
    """Atomically write the latest annotated frame so the viewer never tears."""
    import cv2

    from vision.render import annotate_with_clock

    img = annotate_with_clock(frame, detections, record)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(buf.tobytes())
    os.replace(tmp, path)


def build_config(args) -> PipelineConfig:
    """The live pipeline config, shared with the app via vision.runtime."""
    return live_config(
        {
            "model": args.model,
            "device": args.device,
            "imgsz": args.imgsz,
            "stride": args.stride,
            "conf": args.conf,
        },
        output_path=args.stats,
    )


def start_recorder(path: str, source):
    """Copy the incoming stream to disk alongside analysis.

    A separate ffmpeg process pulls the same URL, so the footage is a faithful
    copy at full frame rate rather than the stride-sampled frames the analyzer
    decodes — and a crash in analysis cannot cost the recording.

    Stream copy only: no re-encode, so this is nearly free. Returns None (with a
    reason) when the source cannot be teed, which is the case for a local camera
    device that cannot be opened twice.
    """
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        print("[live] ffmpeg missing; not recording.", flush=True)
        return None
    if isinstance(source, int) or str(source).isdigit():
        print("[live] a camera device cannot be opened twice; not recording. "
              "Use Voice Backup's screen capture for webcam footage.", flush=True)
        return None

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(source), "-c", "copy", "-f", "mp4",
           "-movflags", "+frag_keyframe+empty_moov", path]
    try:
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    except OSError as exc:
        print(f"[live] could not start the recorder: {exc}", flush=True)
        return None


def stop_recorder(proc, path: str) -> None:
    """Finalise the recording. Fragmented MP4 stays playable even if cut short."""
    import subprocess

    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    size = os.path.getsize(path) if os.path.exists(path) else 0
    print(f"[live] recording saved: {path} ({size / 1024 ** 2:.0f} MB)", flush=True)


def write_status(path: str, payload: dict) -> None:
    """Atomically publish runner health for the app's status chips.

    The app polls this once a second. It stays tiny on purpose — re-reading the
    multi-megabyte match_stats.json at that rate would be wasteful.
    """
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({**payload, "updated": time.time()}, fh)
        os.replace(tmp, path)
    except OSError:
        pass


def build_stats(analyzer: MatchAnalyzer, run_quality: dict = None) -> MatchStats:
    """Assemble the current match document from the analyzer's live state."""
    return MatchStats(
        frame_rate_sampled=analyzer.config.sampled_fps_label(
            getattr(analyzer, "_source_fps", 30.0)
        ),
        frames=getattr(analyzer, "_frames", []),
        passes=analyzer.engine.events,
        possession=analyzer.engine.possession_summary(),
        coordinate_space="pitch" if analyzer.homography is not None else "image",
        run_quality=run_quality or {},
    )


def checkpoint(analyzer: MatchAnalyzer, args, run_quality: dict = None,
               full: bool = True) -> int:
    """Bridge passes into the dashboard and, when ``full``, save the document.

    Returns the number of vision pass events written. Does NOT release the
    capture, so the live loop keeps running after a checkpoint.

    The two halves are deliberately on different cadences. Serialising the
    per-frame tracking data dominates the cost — ~9.5 MB and ~250 ms at the
    4000-frame bound — and that time is a stall on the capture loop, so doing it
    every 10s drops frames all match. The dashboard bridge only reads
    `statistical_events`, which is tiny, so it stays frequent while the full
    document is written on a slower cadence (and always on exit).
    """
    stats = build_stats(analyzer, run_quality)
    if full:
        stats.save(args.stats)

    if not args.no_dashboard:
        events = vbridge.convert(stats.stats_dict())
        vbridge.write_events(events, args.data_file, fresh=False, replace_vision=True)
        return len(events)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="live_vision")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--video", help="YouTube/stream URL or file path.")
    src.add_argument("--camera", type=int,
                     help="Local camera index (a digit string given to --video "
                          "would be read as a file path, so use this instead).")
    p.add_argument("--model", default="soccer_yolov8m_v1.pt", help="YOLO weights.")
    p.add_argument("--device", default="mps", help="'mps', 'cpu', '0', 'cuda'.")
    p.add_argument("--stride", type=int, default=6, help="Process 1 of every N frames.")
    p.add_argument("--imgsz", type=int, default=960, help="Inference image size.")
    p.add_argument("--conf", type=float, default=0.25, help="Detection confidence.")
    p.add_argument("--stats", default="match_stats.json", help="Vision stats output.")
    p.add_argument("--data-file", default="match_data.json", help="Dashboard events.")
    p.add_argument("--interval", type=float, default=10.0,
                   help="Seconds between dashboard bridge checkpoints (cheap).")
    p.add_argument("--full-interval", type=float, default=60.0,
                   help="Seconds between full match_stats.json saves. The "
                        "per-frame tracking data is expensive to serialise and "
                        "the save stalls capture, so it runs less often than "
                        "--interval. A final full save always happens on exit.")
    p.add_argument("--snapshot", default="recordings/live_eye.jpg",
                   help="Write the latest annotated frame here each step "
                        "(set to '' to disable). The Live Eye page displays it.")
    p.add_argument("--no-dashboard", action="store_true",
                   help="Only write match_stats.json (skip dashboard bridging).")
    p.add_argument("--pid-file", default=".live_vision.pid",
                   help="PID file written on start, removed on exit.")
    p.add_argument("--pause-flag", default=".live_eye_paused",
                   help="While this file exists, the runner pauses capture "
                        "(e.g. at half-time) without losing accumulated stats.")
    p.add_argument("--record", default="",
                   help="Also write the incoming stream to this file. A live run "
                        "otherwise leaves no footage at all, so there is nothing "
                        "to clip afterwards. Network sources are copied without "
                        "re-encoding, so this costs almost nothing.")
    p.add_argument("--fixed-camera", action="store_true",
                   help="The camera does not pan, so a saved pitch calibration "
                        "stays valid for the whole match.")
    p.add_argument("--status-file", default="live_eye_status.json",
                   help="Small JSON health file the app polls for live chips.")
    args = p.parse_args(argv)

    # A camera index must stay an int all the way down: resolve_video_source
    # treats the string "0" as a file path.
    source = args.camera if args.camera is not None else args.video

    os.chdir(_REPO_ROOT)
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    pid_path = Path(args.pid_file)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")

    cfg = build_config(args)

    # A fixed camera keeps one calibration valid for the whole match, so load it
    # here and hand it to the analyzer. Without this the run reports "image"
    # space no matter what has been calibrated, and every spatial metric
    # downstream is in frame pixels rather than pitch metres.
    homography = None
    if args.fixed_camera:
        from vision import calibration as vcal

        cal = vcal.load_calibration()
        if cal is None:
            print("[live] --fixed-camera set but no calibration is saved; "
                  "coordinates stay in image space. Calibrate on Camera & Feed.",
                  flush=True)
        else:
            try:
                homography = vcal.homography_from_calibration(cal)
                print(f"[live] pitch calibration loaded "
                      f"({len(cal['points'])} points); coordinates are pitch metres",
                      flush=True)
            except (ValueError, KeyError) as exc:
                print(f"[live] calibration unusable ({exc}); staying in image space",
                      flush=True)

    analyzer = MatchAnalyzer(cfg, homography=homography)
    print(f"[live] opening {source}", flush=True)
    analyzer.open(source)
    print(f"[live] source {analyzer._frame_w}x{analyzer._frame_h} "
          f"@ {analyzer._source_fps:.0f}fps; model={args.model} device={args.device}",
          flush=True)

    from vision.sources import resolve_video_source

    recorder = start_recorder(args.record, source) if args.record else None
    if recorder:
        print(f"[live] recording the feed to {args.record}", flush=True)

    def _release_capture():
        cap = getattr(analyzer, "_cap", None)
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        analyzer._cap = None

    def _reopen_capture():
        # Re-open from the live edge, preserving engine/identities/_frames so
        # the second half continues the same match document.
        fresh = resolve_video_source(source)
        analyzer._resolved_source = fresh
        analyzer._cap = analyzer._open_capture(fresh)

    processed = 0
    ball_seen = 0
    run_started = time.time()
    started = run_started
    last_ckpt = started
    last_full = started      # full document saves are on a slower cadence
    last_status = 0.0        # status is published far more often than checkpoints
    frames_at_baseline = 0   # frame count when the fps window last reset
    paused_seconds = 0.0
    paused_at = None
    paused = False
    was_paused = False

    def run_quality(now=None):
        """How this run is going — the raw material for the trust verdict.

        Saved into match_stats.json so a report generated days later can still
        say whether these numbers were measured or merely indicative. See
        quality.py for the thresholds applied to it.
        """
        now = now or time.time()
        wall = max(1e-6, now - run_started - paused_seconds)
        return {
            "frames_processed": processed,
            "ball_detection_rate": (ball_seen / processed) if processed else 0.0,
            "fps": processed / wall,
            "reconnects": getattr(analyzer, "reconnect_count", 0),
            "duration_seconds": round(now - run_started, 1),
            "paused_seconds": round(paused_seconds, 1),
            "calibrated": analyzer.homography is not None,
            # Declared on Camera & Feed. A calibration is only meaningful while
            # the camera stays still; see quality.assess().
            "fixed_camera": bool(args.fixed_camera),
            "coordinate_space": ("pitch" if analyzer.homography is not None
                                 else "image"),
            "model": args.model,
            "device": args.device,
            "stride": args.stride,
            "imgsz": args.imgsz,
            "source": str(source),
            "source_width": getattr(analyzer, "_frame_w", 0),
            "source_height": getattr(analyzer, "_frame_h", 0),
        }

    def publish_status(now, record=None):
        """Publish runner health. Cheap enough to call every second.

        Deliberately decoupled from checkpointing: a checkpoint rewrites the
        multi-megabyte stats document every 10s, but the app's chips need to go
        live the moment capture starts, not 10s later.
        """
        elapsed = max(1e-6, now - started)
        poss = analyzer.engine.possession_summary()
        write_status(args.status_file, {
            "paused": False,
            "frames": processed,
            "fps": (processed - frames_at_baseline) / elapsed,
            "ball_rate": (ball_seen / processed) if processed else 0.0,
            "passes": len(analyzer.engine.events),
            "possession_home": poss.team_home_percentage,
            "possession_away": poss.team_away_percentage,
            "match_time": record.timestamp if record is not None else "",
            "reconnects": getattr(analyzer, "reconnect_count", 0),
        })

    # Publish once before the first frame so the app flips to "running" as soon
    # as the capture is open, rather than sitting on "starting".
    publish_status(started)

    try:
        while not _STOP:
            # Pause gate: while the flag file exists, stop consuming frames but
            # keep the process (and all accumulated stats) alive.
            if os.path.exists(args.pause_flag):
                if not paused:
                    paused = True
                    paused_at = time.time()
                    _release_capture()
                    # A pause is a natural save point: half-time is exactly when
                    # you might close the laptop.
                    checkpoint(analyzer, args, run_quality(), full=True)
                    print("[live] paused (half-time) — capture released, "
                          "stats preserved.", flush=True)
                # Keep publishing status so the app shows "paused", not "stale".
                write_status(args.status_file,
                             {"paused": True, "frames": processed})
                time.sleep(1.0)
                continue
            if paused:
                paused = False
                was_paused = True
                if paused_at is not None:
                    # Idle time must not count against the run's fps figure, nor
                    # appear as match time: the wall clock keeps running through
                    # half-time and the match does not.
                    idle = time.time() - paused_at
                    paused_seconds += idle
                    analyzer.note_paused(idle)
                    paused_at = None
                _reopen_capture()
                print("[live] resumed — re-opened from the live edge.", flush=True)

            out = analyzer.step()
            if out is None:
                print("[live] stream ended (or reconnect budget exhausted).",
                      flush=True)
                break
            _, _frame, _dets, record = out
            processed += 1
            # The ball carries coordinates only on frames where it was actually
            # detected; status alone is inferred and persists across misses.
            if record.ball.x is not None:
                ball_seen += 1
            if args.snapshot:
                try:
                    write_snapshot(args.snapshot, _frame, _dets, record)
                except Exception as exc:  # never let the viewer kill the run
                    print(f"[live] snapshot failed: {exc}", flush=True)
            now = time.time()
            # Reset the fps baseline after a pause so half-time idling does not
            # drag the reported rate down for the rest of the match.
            if was_paused:
                started, frames_at_baseline = now, processed
                was_paused = False
            if now - last_status >= 1.0:
                publish_status(now, record)
                last_status = now
            if now - last_ckpt >= args.interval:
                full = (now - last_full) >= args.full_interval
                n = checkpoint(analyzer, args, run_quality(now), full=full)
                if full:
                    last_full = now
                poss = analyzer.engine.possession_summary()
                print(f"[live] {record.timestamp}  frames={processed}  "
                      f"passes={len(analyzer.engine.events)}  bridged={n}  "
                      f"poss H{poss.team_home_percentage:.0f}/"
                      f"A{poss.team_away_percentage:.0f}"
                      f"{'  [saved]' if full else ''}", flush=True)
                last_ckpt = now
    finally:
        # The final save always writes the whole document, whatever the cadence.
        n = checkpoint(analyzer, args, run_quality(), full=True)
        try:
            # save=False: close() writes a document without our run_quality
            # block, which would silently clobber the checkpoint just written.
            analyzer.close(save=False)
        except Exception:
            pass
        if recorder is not None:
            stop_recorder(recorder, args.record)
        if pid_path.exists():
            pid_path.unlink()
        # Drop the health file so a later run can't read this match's numbers.
        try:
            os.remove(args.status_file)
        except OSError:
            pass
        print(f"[live] stopped. final: frames={processed} "
              f"passes={len(analyzer.engine.events)} bridged={n} "
              f"-> {args.stats}, {args.data_file}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())