#!/usr/bin/env python3
"""Kickoff Pulse — shared vision runtime helpers.

Device selection and pipeline-config construction, in one place so the three
callers agree on what a run looks like:

  * ``pages/Camera_and_Feed.py`` — configures the feed before kickoff
  * ``scripts/live_vision.py``   — the persistent live runner (the Eye)
  * ``pages/Film_Room.py``       — recorded-file analysis

Before this module each of those built its own ``PipelineConfig``, so a setting
tuned in the UI did not necessarily reach the live runner. Kept free of heavy
imports (torch is probed lazily) so importing it stays cheap.
"""

from __future__ import annotations

from .config import PipelineConfig

# Device ids as Ultralytics wants them, keyed by the label the UI shows.
DEVICE_CHOICES = ("auto", "cpu", "mps", "0")

DEVICE_LABELS = {
    "auto": "Auto",
    "cpu": "CPU",
    "mps": "MPS (Apple Silicon)",
    "0": "CUDA GPU 0",
}


def best_device() -> str:
    """The best available torch device: cuda > mps > cpu."""
    try:
        import torch

        if torch.cuda.is_available():
            return "0"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def resolve_device(choice: str) -> str:
    """Turn a stored device choice ("auto", "mps", ...) into a concrete device."""
    choice = (choice or "auto").strip()
    return best_device() if choice in ("", "auto") else choice


def live_config(feed: dict, output_path: str = "match_stats.json") -> PipelineConfig:
    """Build the pipeline config for an open-ended live run from ``control.feed``.

    Live runs differ from file runs in two ways that matter: OCR is off (it is
    too slow to keep up with a real-time feed), and the recorded frame buffer is
    bounded so a 90-minute match cannot grow the process without limit.
    Possession and passing keep accumulating for the whole match regardless.
    """
    feed = feed or {}
    stride = max(1, int(feed.get("stride", 6) or 6))
    return PipelineConfig(
        model_path=str(feed.get("model") or "soccer_yolov8m_v1.pt"),
        device=resolve_device(feed.get("device", "auto")),
        detection_imgsz=int(feed.get("imgsz", 960) or 960),
        frame_stride=stride,
        detection_conf=float(feed.get("conf", 0.25) or 0.25),
        ocr_enabled=False,
        possession_frames=max(6, 60 // stride),
        # ~13 minutes of sampled frames at stride 6; a bound, not a match limit.
        max_frames_recorded=4000,
        output_path=output_path,
    )
