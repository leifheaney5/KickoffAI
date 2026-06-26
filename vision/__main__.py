#!/usr/bin/env python3
"""Kickoff Pulse — vision pipeline command-line interface.

Usage examples
--------------
Quick demo on a stock model (players + ball, no calibration)::

    python -m vision --video match.mp4

Calibrated run with four pitch reference points and a fine-tuned model::

    python -m vision --video match.mp4 \\
        --model models/soccer_yolov8x.pt --tracker botsort \\
        --points "120,80;1800,75;1850,1000;90,1010" \\
        --output match_stats.json --device cuda
"""

from __future__ import annotations

import argparse
from typing import List, Optional, Tuple

from .config import PipelineConfig
from .homography import PitchHomography
from .pipeline import MatchAnalyzer
from .schema import FrameRecord


def _parse_points(raw: Optional[str]) -> Optional[List[Tuple[float, float]]]:
    """Parse ``"x1,y1;x2,y2;x3,y3;x4,y4"`` into a list of four points."""
    if not raw:
        return None
    points: List[Tuple[float, float]] = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        x_str, y_str = chunk.split(",")
        points.append((float(x_str), float(y_str)))
    if len(points) != 4:
        raise argparse.ArgumentTypeError(
            "--points needs exactly four 'x,y' pairs separated by ';'"
        )
    return points


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m vision",
        description="Local soccer video analysis -> match_stats.json",
    )
    p.add_argument(
        "--video", required=True,
        help="Path, direct stream URL, or YouTube URL for the match video.",
    )
    p.add_argument("--output", default="match_stats.json", help="Output JSON path.")
    p.add_argument("--model", default="yolov8x.pt", help="YOLO model weights.")
    p.add_argument(
        "--tracker", default="botsort", choices=["botsort", "bytetrack"],
        help="Multi-object tracker.",
    )
    p.add_argument("--device", default="", help="'cpu', 'cuda', '0', 'mps', ...")
    p.add_argument(
        "--roboflow-model", default="",
        help="Use a Roboflow model instead of --model, e.g. "
        "'football-players-detection-3zvbc/12' (needs ROBOFLOW_API_KEY).",
    )
    p.add_argument(
        "--roboflow-url", default="https://serverless.roboflow.com",
        help="Roboflow inference endpoint.",
    )
    p.add_argument(
        "--pitch-model", default="",
        help="Per-frame pitch homography via a Roboflow keypoint model "
        "(handles panning cameras). Use 'auto' for the default, or an explicit "
        "id like 'football-field-detection-f07vi/14'. Needs ROBOFLOW_API_KEY.",
    )
    p.add_argument(
        "--stride", type=int, default=3,
        help="Process 1 of every N frames (3 -> ~10fps from 30fps source).",
    )
    p.add_argument("--conf", type=float, default=0.25, help="Detection confidence.")
    p.add_argument(
        "--imgsz", type=int, default=1280,
        help="Inference image size (smaller = faster on CPU, e.g. 640).",
    )
    p.add_argument(
        "--points", type=str, default=None,
        help="Four image 'x,y' pairs (';'-separated) of pitch landmarks.",
    )
    p.add_argument(
        "--pitch-points", type=str, default=None,
        help="Matching four pitch 'x,y' pairs in metres (default: corners).",
    )
    p.add_argument(
        "--possession-radius", type=float, default=None,
        help="Override possession_radius_m. For UNCALIBRATED runs (no --points), "
        "coordinates are normalised 0..100 image space, so the default 1.5 'm' is "
        "far too tight; try 4-10 to make possession/passing fire.",
    )
    p.add_argument(
        "--min-pass-distance", type=float, default=None,
        help="Override min_pass_distance_m (same image-space caveat as "
        "--possession-radius for uncalibrated runs).",
    )
    p.add_argument(
        "--possession-frames", type=int, default=None,
        help="Override possession_frames (consecutive same-track frames to "
        "confirm a holder). The default 15 never survives a panning camera's "
        "track-id churn; 3-5 is realistic for Veo-style auto-follow footage.",
    )
    p.add_argument("--no-ocr", action="store_true", help="Disable jersey OCR.")
    p.add_argument("--gpu-ocr", action="store_true", help="Use GPU for OCR.")
    p.add_argument("--show", action="store_true", help="Show a debug overlay.")
    p.add_argument(
        "--max-seconds", type=float, default=0.0,
        help="Stop after N seconds of footage (debugging).",
    )
    p.add_argument("--quiet", action="store_true", help="Suppress progress output.")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    # Team K-Means clusters torso colours and can hit degenerate (near-empty)
    # crops, which numpy surfaces as a flood of divide-by-zero / overflow
    # RuntimeWarnings in matmul. They are harmless to the result but bury the
    # progress output, so silence them for the CLI run.
    import warnings

    warnings.filterwarnings("ignore", category=RuntimeWarning)

    config = PipelineConfig(
        model_path=args.model,
        output_path=args.output,
        device=args.device,
        tracker=args.tracker,
        roboflow_model=args.roboflow_model,
        roboflow_api_url=args.roboflow_url,
        frame_stride=args.stride,
        detection_conf=args.conf,
        detection_imgsz=args.imgsz,
        ocr_enabled=not args.no_ocr,
        use_gpu_ocr=args.gpu_ocr,
        show=args.show,
        max_seconds=args.max_seconds,
    )
    # Uncalibrated footage (no --points) emits 0..100 image-space coordinates,
    # where the metric possession/passing thresholds are meaningless; let the
    # caller widen them so the heuristics actually fire.
    if args.possession_radius is not None:
        config.possession_radius_m = args.possession_radius
    if args.min_pass_distance is not None:
        config.min_pass_distance_m = args.min_pass_distance
    if args.possession_frames is not None:
        config.possession_frames = max(1, args.possession_frames)

    homography = None
    image_points = _parse_points(args.points)
    if image_points is not None:
        pitch_points = _parse_points(args.pitch_points)
        homography = PitchHomography(
            image_points,
            pitch_points,
            pitch_length_m=config.pitch_length_m,
            pitch_width_m=config.pitch_width_m,
        )
    elif not args.quiet:
        print(
            "[vision] No --points given: using uncalibrated image-space "
            "coordinates (relative positions only)."
        )

    # Lightweight progress: a heartbeat every 50 processed frames.
    state = {"n": 0}

    def _on_frame(record: FrameRecord) -> None:
        state["n"] += 1
        if not args.quiet and state["n"] % 50 == 0:
            print(
                f"[vision] {record.timestamp}  frame {record.frame_index}  "
                f"players={len(record.players)}  ball={record.ball.status}"
            )

    pitch_detector = None
    if args.pitch_model:
        from .pitch import DEFAULT_PITCH_MODEL, PitchDetector

        mid = (
            DEFAULT_PITCH_MODEL
            if args.pitch_model in ("auto", "default")
            else args.pitch_model
        )
        pitch_detector = PitchDetector(config, mid)

    analyzer = MatchAnalyzer(
        config, homography, on_frame=_on_frame, pitch_detector=pitch_detector
    )
    stats = analyzer.run(args.video)

    if not args.quiet:
        poss = stats.possession
        print(
            f"\n[vision] Done. frames={len(stats.frames)}  "
            f"passes={len(stats.passes)}  "
            f"possession Home {poss.team_home_percentage:.1f}% / "
            f"Away {poss.team_away_percentage:.1f}%"
        )
        print(f"[vision] Wrote {config.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
