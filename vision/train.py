#!/usr/bin/env python3
"""Kickoff Pulse — train a soccer-specific YOLO model.

The vision pipeline is built around four classes — ``player``, ``ball``,
``referee``, ``jersey_number``. A stock COCO model only offers ``person`` /
``sports ball`` (which the pipeline aliases), so it cannot see referees or
jersey numbers and detects the ball poorly. For real match analysis you want
weights fine-tuned on soccer footage.

This helper:

1. (optionally) downloads a Roboflow Universe soccer dataset, and
2. fine-tunes a YOLO model on it.

Datasets: https://universe.roboflow.com/browse/sports/soccer
A widely-used project is "football-players-detection" (classes: ``ball``,
``goalkeeper``, ``player``, ``referee`` — ``goalkeeper`` folds into ``player``
via the pipeline's class aliases). Jersey numbers are a separate dataset/head;
train a second model for them and point ``PipelineConfig`` at it if desired.

.. important::
   Training is only practical on a CUDA **GPU**. On CPU (``--device cpu``) a
   real run takes many hours to days — use it solely for a tiny ``--epochs 1``
   smoke test of the wiring.

Examples
--------
Download from Roboflow, then train (GPU 0)::

    python -m vision.train --api-key $ROBOFLOW_API_KEY \\
        --workspace roboflow-jvuqo --project football-players-detection-3zvbc \\
        --version 12 --base yolov8x.pt --epochs 100 --imgsz 1280 --device 0

Train on an already-downloaded dataset::

    python -m vision.train --data datasets/soccer/data.yaml \\
        --base yolov8x.pt --epochs 100 --device 0
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional


def download_dataset(
    api_key: str,
    workspace: str,
    project: str,
    version: int,
    fmt: str = "yolov8",
    location: Optional[str] = None,
) -> str:
    """Download a Roboflow dataset and return the path to its ``data.yaml``."""
    try:
        from roboflow import Roboflow
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ImportError(
            "The 'roboflow' package is required to download datasets. Install "
            "the vision extras: pip install -r vision/requirements.txt"
        ) from exc

    rf = Roboflow(api_key=api_key)
    proj = rf.workspace(workspace).project(project)
    dataset = proj.version(version).download(fmt, location=location)
    data_yaml = os.path.join(dataset.location, "data.yaml")
    print(f"[train] dataset downloaded -> {dataset.location}")
    return data_yaml


def train(
    data_yaml: str,
    base: str = "yolov8x.pt",
    epochs: int = 100,
    imgsz: int = 1280,
    device: str = "0",
    batch: int = -1,
    workers: int = 8,
    project: str = "runs/soccer",
    name: str = "kickoff_pulse",
) -> str:
    """Fine-tune a YOLO model; return the path to the best weights."""
    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ImportError(
            "Ultralytics is required for training. Install the vision extras: "
            "pip install -r vision/requirements.txt"
        ) from exc

    if not os.path.exists(data_yaml):
        raise FileNotFoundError(f"data.yaml not found: {data_yaml}")

    model = YOLO(base)
    results = model.train(
        data=data_yaml,
        epochs=epochs,
        imgsz=imgsz,
        device=device,
        batch=batch,
        workers=workers,
        project=project,
        name=name,
    )
    save_dir = getattr(results, "save_dir", None) or os.path.join(project, name)
    best = os.path.join(str(save_dir), "weights", "best.pt")
    return best


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m vision.train",
        description="Fine-tune a soccer YOLO model for the vision pipeline.",
    )
    # Data source: either a local data.yaml, or Roboflow download args.
    p.add_argument("--data", default=None, help="Path to an existing data.yaml.")
    p.add_argument(
        "--api-key", default=os.environ.get("ROBOFLOW_API_KEY"),
        help="Roboflow API key (or set ROBOFLOW_API_KEY).",
    )
    p.add_argument("--workspace", default=None, help="Roboflow workspace slug.")
    p.add_argument("--project", default=None, help="Roboflow project slug.")
    p.add_argument("--version", type=int, default=None, help="Dataset version.")
    p.add_argument(
        "--location", default=None, help="Where to download the dataset."
    )
    # Training hyper-parameters.
    p.add_argument("--base", default="yolov8x.pt", help="Base weights to fine-tune.")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--imgsz", type=int, default=1280)
    p.add_argument("--batch", type=int, default=-1, help="-1 = auto batch size.")
    p.add_argument("--workers", type=int, default=8,
                   help="Dataloader workers (lower if you hit CPU RAM limits).")
    p.add_argument("--device", default="0", help="'0' GPU, '0,1' multi, 'cpu'.")
    p.add_argument("--run-project", default="runs/soccer", help="Output dir.")
    p.add_argument("--name", default="kickoff_pulse", help="Run name.")
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)

    data_yaml = args.data
    if not data_yaml:
        missing = [
            flag
            for flag, val in [
                ("--api-key", args.api_key),
                ("--workspace", args.workspace),
                ("--project", args.project),
                ("--version", args.version),
            ]
            if not val
        ]
        if missing:
            print(
                "[train] provide --data <data.yaml>, OR all of "
                "--api-key/--workspace/--project/--version to download from "
                f"Roboflow. Missing: {', '.join(missing)}",
                file=sys.stderr,
            )
            return 2
        data_yaml = download_dataset(
            args.api_key, args.workspace, args.project, args.version,
            location=args.location,
        )

    if args.device == "cpu":
        print(
            "[train] WARNING: training on CPU is impractically slow; use a GPU "
            "(--device 0). Proceeding anyway (use --epochs 1 to smoke-test)."
        )

    best = train(
        data_yaml,
        base=args.base,
        epochs=args.epochs,
        imgsz=args.imgsz,
        device=args.device,
        batch=args.batch,
        workers=args.workers,
        project=args.run_project,
        name=args.name,
    )
    print(f"\n[train] best weights: {best}")
    print(f"[train] use them:  python -m vision --video match.mp4 --model {best}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
