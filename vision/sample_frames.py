#!/usr/bin/env python3
"""Kickoff Pulse — frame sampler for dataset building (Phase 3 groundwork).

Pulls evenly-spaced frames out of a match video so you can upload them to
Roboflow (or any labeller) and annotate ball / player / referee / jersey_number
on *your own* footage. Closing the domain gap to your Veo youth clips is what
makes the trained model actually work where stock/cloud models struggle.

Frames are sampled by seeking (not full decode), so it stays fast even on a
multi-hour match.

Example
-------
    python -m vision.sample_frames --video match.mp4 --out annotation_frames \\
        --count 300

Then upload ``annotation_frames/`` to a Roboflow project, label, and train with
``vision/train.py``.
"""

from __future__ import annotations

import argparse
import os
from typing import Optional


def sample_frames(
    video: str,
    out_dir: str = "annotation_frames",
    count: int = 200,
    start_seconds: float = 0.0,
    end_seconds: float = 0.0,
    quality: int = 95,
) -> int:
    """Save ``count`` evenly-spaced JPEG frames from ``video`` into ``out_dir``.

    ``start_seconds`` / ``end_seconds`` (0 = video end) restrict the sampling
    window. Returns the number of frames written.
    """
    import cv2

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video: {video}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    first = int(start_seconds * fps)
    last = int(end_seconds * fps) if end_seconds > 0 else total
    last = min(last, total) if total else last
    span = max(1, last - first)
    step = max(1, span // max(1, count))

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(video))[0]
    saved = 0
    for k in range(count):
        fno = first + k * step
        if total and fno >= last:
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, fno)
        ok, frame = cap.read()
        if not ok:
            break
        path = os.path.join(out_dir, f"{stem}_f{fno:07d}.jpg")
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
        saved += 1
    cap.release()
    return saved


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m vision.sample_frames",
        description="Extract frames from a match video for annotation.",
    )
    p.add_argument("--video", required=True, help="Path to the match video.")
    p.add_argument("--out", default="annotation_frames", help="Output folder.")
    p.add_argument("--count", type=int, default=200, help="Frames to extract.")
    p.add_argument("--start", type=float, default=0.0, help="Start second.")
    p.add_argument("--end", type=float, default=0.0, help="End second (0=end).")
    p.add_argument("--quality", type=int, default=95, help="JPEG quality 1-100.")
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    n = sample_frames(args.video, args.out, args.count,
                      args.start, args.end, args.quality)
    print(f"[sample] wrote {n} frame(s) -> {args.out}/")
    print("[sample] next: upload to a Roboflow project, annotate "
          "ball/player/referee/jersey_number, then train with vision/train.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
