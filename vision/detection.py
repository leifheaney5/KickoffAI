#!/usr/bin/env python3
"""Kickoff Pulse — object detection + base tracking.

A thin, well-typed wrapper around Ultralytics YOLO. Ultralytics bundles the
BoT-SORT and ByteTrack trackers, so a single ``model.track(...)`` call gives us
both detections *and* per-object track ids. The heavier identity-permanence
logic that survives long occlusions lives in :mod:`vision.tracking`.

Ultralytics / torch are imported lazily inside :class:`Detector` so the rest of
the package (geometry, heuristics, schema) imports without a GPU stack present.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .config import PipelineConfig, canonical_class

BBox = Tuple[float, float, float, float]  # x1, y1, x2, y2


# --------------------------------------------------------------------------- #
# Bounding-box geometry helpers (shared across the package)
# --------------------------------------------------------------------------- #
def bbox_center(box: BBox) -> Tuple[float, float]:
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def bbox_foot(box: BBox) -> Tuple[float, float]:
    """Bottom-centre of the box — a player's feet, i.e. their pitch contact."""
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, y2)


def bbox_area(box: BBox) -> float:
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def bbox_contains(outer: BBox, inner: BBox, tol: float = 2.0) -> bool:
    """True if ``inner`` lies (almost) entirely within ``outer``."""
    return (
        inner[0] >= outer[0] - tol
        and inner[1] >= outer[1] - tol
        and inner[2] <= outer[2] + tol
        and inner[3] <= outer[3] + tol
    )


# --------------------------------------------------------------------------- #
@dataclass
class Detection:
    """A single detected object in one frame."""

    cls_name: str                 # canonical class (player/ball/referee/...)
    confidence: float
    box: BBox
    track_id: Optional[int] = None

    @property
    def center(self) -> Tuple[float, float]:
        return bbox_center(self.box)

    @property
    def foot(self) -> Tuple[float, float]:
        return bbox_foot(self.box)

    @property
    def area(self) -> float:
        return bbox_area(self.box)


class Detector:
    """Loads a YOLO model once and runs detection-with-tracking per frame."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self._model = None        # lazily constructed Ultralytics YOLO

    # ------------------------------------------------------------------ #
    def _ensure_model(self):
        if self._model is None:
            try:
                from ultralytics import YOLO
            except ImportError as exc:  # pragma: no cover - dependency guard
                raise ImportError(
                    "Ultralytics is required for detection. Install the vision "
                    "extras: pip install -r vision/requirements.txt"
                ) from exc
            self._model = YOLO(self.config.model_path)
        return self._model

    @property
    def class_names(self) -> Dict[int, str]:
        """Raw class-id -> name map reported by the loaded model."""
        return dict(self._ensure_model().names)

    # ------------------------------------------------------------------ #
    def track(self, frame: np.ndarray) -> List[Detection]:
        """Detect + track on a single frame, returning canonical detections.

        Uses Ultralytics' streaming tracker state (``persist=True``) so track
        ids stay consistent across successive calls.
        """
        model = self._ensure_model()
        results = model.track(
            frame,
            persist=True,
            tracker=self.config.tracker_yaml,
            conf=self.config.detection_conf,
            imgsz=self.config.detection_imgsz,
            device=self.config.device or None,
            verbose=False,
        )
        return self._parse(results)

    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Detect without tracking (track_id is always ``None``)."""
        model = self._ensure_model()
        results = model.predict(
            frame,
            conf=self.config.detection_conf,
            imgsz=self.config.detection_imgsz,
            device=self.config.device or None,
            verbose=False,
        )
        return self._parse(results)

    # ------------------------------------------------------------------ #
    def _parse(self, results) -> List[Detection]:
        detections: List[Detection] = []
        if not results:
            return detections
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None or boxes.shape[0] == 0:
            return detections

        names = result.names                      # raw id -> name for this run
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        clss = boxes.cls.cpu().numpy().astype(int)
        ids = (
            boxes.id.cpu().numpy().astype(int)
            if getattr(boxes, "id", None) is not None
            else None
        )

        for i in range(len(xyxy)):
            canonical = canonical_class(names.get(int(clss[i]), clss[i]))
            if canonical is None:
                continue                           # ignore non-soccer classes
            detections.append(
                Detection(
                    cls_name=canonical,
                    confidence=float(confs[i]),
                    box=tuple(float(v) for v in xyxy[i]),
                    track_id=int(ids[i]) if ids is not None else None,
                )
            )
        return detections


def split_by_class(detections: List[Detection]) -> Dict[str, List[Detection]]:
    """Group detections into ``player`` / ``ball`` / ``referee`` / ``jersey``."""
    grouped: Dict[str, List[Detection]] = {}
    for det in detections:
        grouped.setdefault(det.cls_name, []).append(det)
    return grouped
