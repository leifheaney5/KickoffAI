#!/usr/bin/env python3
"""Kickoff Pulse — Roboflow detection backend.

A drop-in alternative to :class:`vision.detection.Detector` that runs a
Roboflow-hosted (or Roboflow-trained) soccer model instead of a local
Ultralytics model. It exposes the same ``track(frame)`` / ``detect(frame)``
interface returning :class:`~vision.detection.Detection` objects, so the rest of
the pipeline is unchanged.

The Roboflow model only performs detection, so this backend pairs it with
Supervision's **ByteTrack** to supply consistent track ids (the pipeline's
identity-permanence layer still sits on top of that).

.. note::
   Using ``serverless.roboflow.com`` sends each frame to Roboflow's cloud and
   consumes free-tier inference credits — great for a quick evaluation, but it
   is *not* local inference. A free Roboflow API key is required either way
   (set ``ROBOFLOW_API_KEY`` or ``PipelineConfig.roboflow_api_key``).

The widely-used model id is ``football-players-detection-3zvbc/<version>``
(classes: ball, goalkeeper, player, referee — folded onto the pipeline's
canonical labels via :func:`~vision.config.canonical_class`).
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

import numpy as np

from .config import PipelineConfig, canonical_class
from .detection import Detection

# Stable canonical-name <-> class-id map used to round-trip through ByteTrack.
_NAME_TO_ID = {"player": 0, "ball": 1, "referee": 2, "jersey_number": 3}
_ID_TO_NAME = {v: k for k, v in _NAME_TO_ID.items()}


class RoboflowDetector:
    """Detection via a Roboflow model + ByteTrack ids (Detector-compatible)."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.model_id = config.roboflow_model
        self._client = None
        self._tracker = None
        self.errors = 0          # transient inference failures (network/quota)

    # ------------------------------------------------------------------ #
    def _ensure(self):
        if self._client is not None:
            return
        try:
            from inference_sdk import InferenceHTTPClient
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ImportError(
                "inference-sdk is required for the Roboflow backend: "
                "pip install inference-sdk"
            ) from exc
        try:
            import supervision as sv
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ImportError(
                "supervision is required for ByteTrack: "
                "pip install -r vision/requirements.txt"
            ) from exc

        key = self.config.roboflow_api_key or os.environ.get("ROBOFLOW_API_KEY", "")
        if not key:
            raise ValueError(
                "No Roboflow API key. Set ROBOFLOW_API_KEY (free key from "
                "roboflow.com -> Settings -> API key) or PipelineConfig."
                "roboflow_api_key."
            )
        if not self.model_id:
            raise ValueError(
                "No Roboflow model id. Set PipelineConfig.roboflow_model, e.g. "
                "'football-players-detection-3zvbc/12'."
            )
        self._client = InferenceHTTPClient(
            api_url=self.config.roboflow_api_url, api_key=key
        )
        self._tracker = sv.ByteTrack()

    # ------------------------------------------------------------------ #
    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Run the Roboflow model on one frame (no track ids)."""
        self._ensure()
        try:
            result = self._client.infer(frame, model_id=self.model_id)
        except Exception as exc:  # network blip, rate limit, quota, ...
            self.errors += 1
            if self.errors <= 3:
                print(f"[roboflow] inference error ({self.errors}): {exc}")
            return []
        return self._parse(result)

    def track(self, frame: np.ndarray) -> List[Detection]:
        """Detect via Roboflow, then assign ids with ByteTrack."""
        import supervision as sv

        self._ensure()
        detections = self.detect(frame)
        if not detections:
            # Still advance the tracker so its motion models stay in sync.
            self._tracker.update_with_detections(sv.Detections.empty())
            return []

        xyxy = np.array([d.box for d in detections], dtype=np.float32)
        conf = np.array([d.confidence for d in detections], dtype=np.float32)
        class_id = np.array(
            [_NAME_TO_ID.get(d.cls_name, 0) for d in detections], dtype=int
        )
        sv_dets = sv.Detections(xyxy=xyxy, confidence=conf, class_id=class_id)
        tracked = self._tracker.update_with_detections(sv_dets)

        out: List[Detection] = []
        for i in range(len(tracked)):
            tid = tracked.tracker_id[i] if tracked.tracker_id is not None else None
            out.append(
                Detection(
                    cls_name=_ID_TO_NAME.get(int(tracked.class_id[i]), "player"),
                    confidence=float(tracked.confidence[i]),
                    box=tuple(float(v) for v in tracked.xyxy[i]),
                    track_id=int(tid) if tid is not None else None,
                )
            )
        return out

    # ------------------------------------------------------------------ #
    def _parse(self, result) -> List[Detection]:
        """Map a Roboflow inference response to canonical detections."""
        # Roboflow may return a dict, or a list (workflow / batch) of dicts.
        if isinstance(result, list):
            result = result[0] if result else {}
        predictions = (result or {}).get("predictions", []) or []

        detections: List[Detection] = []
        for pred in predictions:
            canonical = canonical_class(pred.get("class"))
            if canonical is None:
                continue
            conf = float(pred.get("confidence", 0.0))
            if conf < self.config.detection_conf:
                continue
            # Roboflow boxes are centre-x/centre-y + width/height.
            cx = float(pred["x"])
            cy = float(pred["y"])
            w = float(pred["width"])
            h = float(pred["height"])
            box = (cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)
            detections.append(Detection(canonical, conf, box))
        return detections
