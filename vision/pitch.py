#!/usr/bin/env python3
"""Kickoff Pulse — per-frame pitch homography.

On a panning / zooming camera a single static homography is wrong the moment the
camera moves. This module detects pitch landmarks **every frame** (via a
Roboflow keypoint model) and rebuilds the image->pitch homography from whatever
landmarks are confidently visible, so player/ball positions stay anchored to the
real pitch as the camera moves.

It reuses Roboflow's reference :class:`SoccerPitchConfiguration` (32 standard
pitch vertices, in cm) as the destination template, matched index-for-index to
the model's keypoint output.

.. note::
   The pitch model needs visible standard pitch markings. On non-standard
   surfaces (e.g. a soccer match painted over an American-football field) it may
   detect nothing — the pipeline then falls back to the last good homography, or
   to image-space coordinates.
"""

from __future__ import annotations

import os
from typing import List, Optional

import numpy as np

from .config import PipelineConfig
from .homography import PitchHomography

DEFAULT_PITCH_MODEL = "football-field-detection-f07vi/14"

_PITCH_CONFIG = None


def _pitch_config():
    """Lazily load Roboflow's SoccerPitchConfiguration (32 vertices, cm)."""
    global _PITCH_CONFIG
    if _PITCH_CONFIG is None:
        try:
            from sports.configs.soccer import SoccerPitchConfiguration
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ImportError(
                "The 'sports' package is required for pitch homography: "
                "pip install git+https://github.com/roboflow/sports.git"
            ) from exc
        _PITCH_CONFIG = SoccerPitchConfiguration()
    return _PITCH_CONFIG


def homography_from_keypoints(
    keypoints: List[dict], conf_threshold: float = 0.5
) -> Optional[PitchHomography]:
    """Build a :class:`PitchHomography` from detected pitch keypoints.

    ``keypoints`` is the model's per-vertex list (index-aligned with the pitch
    template). Vertices below ``conf_threshold`` (not visible this frame) are
    skipped. Returns ``None`` if fewer than four landmarks are usable.
    """
    cfg = _pitch_config()
    vertices = cfg.vertices
    src: List[List[float]] = []
    dst: List[List[float]] = []
    for i, kp in enumerate(keypoints):
        if i >= len(vertices):
            break
        if float(kp.get("confidence", 0.0)) < conf_threshold:
            continue
        src.append([float(kp["x"]), float(kp["y"])])
        vx, vy = vertices[i]
        dst.append([vx / 100.0, vy / 100.0])   # cm -> m
    if len(src) < 4:
        return None
    try:
        return PitchHomography.from_correspondences(
            src, dst, cfg.length / 100.0, cfg.width / 100.0
        )
    except ValueError:
        return None


class PitchDetector:
    """Roboflow keypoint model that locates pitch landmarks per frame."""

    def __init__(
        self, config: PipelineConfig, model_id: Optional[str] = None
    ) -> None:
        self.config = config
        self.model_id = model_id or DEFAULT_PITCH_MODEL
        self._client = None
        self.errors = 0
        self.empty = 0          # frames where no pitch was detected

    def _ensure(self):
        if self._client is not None:
            return
        from inference_sdk import InferenceHTTPClient

        key = self.config.roboflow_api_key or os.environ.get("ROBOFLOW_API_KEY", "")
        if not key:
            raise ValueError(
                "No Roboflow API key for pitch detection. Set ROBOFLOW_API_KEY."
            )
        self._client = InferenceHTTPClient(
            api_url=self.config.roboflow_api_url, api_key=key
        )

    def keypoints(self, frame: np.ndarray) -> Optional[List[dict]]:
        """Return the per-vertex keypoint list for a frame, or ``None``."""
        self._ensure()
        try:
            result = self._client.infer(frame, model_id=self.model_id)
        except Exception as exc:
            self.errors += 1
            if self.errors <= 3:
                print(f"[pitch] inference error ({self.errors}): {exc}")
            return None
        preds = result.get("predictions") if isinstance(result, dict) else result
        if isinstance(preds, list):
            preds = preds[0] if preds else None
        if not preds:
            self.empty += 1
            return None
        return preds.get("keypoints")

    def homography(
        self, frame: np.ndarray, conf_threshold: float = 0.5
    ) -> Optional[PitchHomography]:
        """Detect landmarks and build this frame's homography (or ``None``)."""
        kps = self.keypoints(frame)
        if not kps:
            return None
        return homography_from_keypoints(kps, conf_threshold)
