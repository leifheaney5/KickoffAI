#!/usr/bin/env python3
"""Kickoff Pulse — fixed-camera pitch calibration (Phase 2).

A Veo-style broadcast camera does not pan, so a single image->pitch homography
holds for the whole match. Rather than detecting pitch landmarks every frame
(needed only for panning cameras), the user marks a handful of known points
once; this module persists those correspondences and rebuilds a static
:class:`~vision.homography.PitchHomography` from them.

Coordinate convention (matches the schema and tactical map): normalised 0..100,
with ``x`` along the pitch length (0 = left goal line, 100 = right goal line)
and ``y`` across the width (0 = top touchline, 100 = bottom touchline).
"""

from __future__ import annotations

import json
import os
import time
from typing import List, Optional

from .homography import PitchHomography

DEFAULT_CALIBRATION_PATH = "pitch_calibration.json"

# FIFA-standard penalty area on a 105 x 68 m pitch, expressed in 0..100 units:
#   depth 16.5 m  -> 15.71 along the length;  width 40.32 m centred on 68 m
#   -> spans 20.35 .. 79.65 across the width.
_PA_FRONT_L = 16.5 / 105.0 * 100.0          # 15.71
_PA_FRONT_R = 100.0 - _PA_FRONT_L           # 84.29
_PA_TOP = (68.0 - 40.32) / 2.0 / 68.0 * 100.0   # 20.35
_PA_BOT = 100.0 - _PA_TOP                        # 79.65

# Named landmarks the user can pick from, with their fixed normalised position.
# Kept to unambiguous, easy-to-click points so calibration stays accurate.
LANDMARKS = {
    "Top-left corner": (0.0, 0.0),
    "Top-right corner": (100.0, 0.0),
    "Bottom-right corner": (100.0, 100.0),
    "Bottom-left corner": (0.0, 100.0),
    "Halfway line x top touchline": (50.0, 0.0),
    "Halfway line x bottom touchline": (50.0, 100.0),
    "Centre spot": (50.0, 50.0),
    "Left box front x top": (_PA_FRONT_L, _PA_TOP),
    "Left box front x bottom": (_PA_FRONT_L, _PA_BOT),
    "Right box front x top": (_PA_FRONT_R, _PA_TOP),
    "Right box front x bottom": (_PA_FRONT_R, _PA_BOT),
}

# A sensible default 4-point set: the pitch corners, in TL, TR, BR, BL order.
DEFAULT_LANDMARK_ORDER = [
    "Top-left corner",
    "Top-right corner",
    "Bottom-right corner",
    "Bottom-left corner",
]


def validate_points(points: List[dict]) -> Optional[str]:
    """Return an error message if ``points`` can't form a homography, else None.

    Needs at least four correspondences whose image points are not all collinear
    (a zero-area spread can't define a perspective transform).
    """
    if len(points) < 4:
        return f"Need at least 4 points; have {len(points)}."
    labels = [p.get("label") for p in points]
    if len(set(labels)) < len(labels):
        return "Each landmark may only be used once."
    xs = [p["px"][0] for p in points]
    ys = [p["px"][1] for p in points]
    if (max(xs) - min(xs)) < 1 or (max(ys) - min(ys)) < 1:
        return "Picked points are collinear; spread them across the pitch."
    return None


def homography_from_calibration(
    cal: dict,
    pitch_length_m: float = 105.0,
    pitch_width_m: float = 68.0,
) -> PitchHomography:
    """Rebuild a static :class:`PitchHomography` from a saved calibration dict."""
    points = cal["points"]
    err = validate_points(points)
    if err:
        raise ValueError(err)
    image_pts = [p["px"] for p in points]
    norm_pts = [p["norm"] for p in points]
    if len(points) == 4:
        return PitchHomography.from_normalised_points(
            image_pts, norm_pts, pitch_length_m, pitch_width_m
        )
    # >4 points: convert normalised -> metres and fit robustly via RANSAC.
    metres = [
        [x / 100.0 * pitch_length_m, y / 100.0 * pitch_width_m]
        for x, y in norm_pts
    ]
    return PitchHomography.from_correspondences(
        image_pts, metres, pitch_length_m, pitch_width_m
    )


def save_calibration(
    points: List[dict],
    frame_size: Optional[tuple] = None,
    path: str = DEFAULT_CALIBRATION_PATH,
    source: str = "",
) -> dict:
    """Persist the picked correspondences (image px + normalised pitch) to JSON.

    ``points`` is a list of ``{"label": str, "norm": [x, y], "px": [x, y]}`` in
    full-resolution image pixels. Raises ``ValueError`` if the set is invalid.
    """
    err = validate_points(points)
    if err:
        raise ValueError(err)
    cal = {
        "version": 1,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "frame_size": list(frame_size) if frame_size else None,
        "points": points,
    }
    with open(path, "w") as fh:
        json.dump(cal, fh, indent=2)
    return cal


def load_calibration(path: str = DEFAULT_CALIBRATION_PATH) -> Optional[dict]:
    """Load a saved calibration, or None if absent / unreadable."""
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            cal = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not cal.get("points"):
        return None
    return cal


def clear_calibration(path: str = DEFAULT_CALIBRATION_PATH) -> bool:
    """Delete the saved calibration file. True if a file was removed."""
    if os.path.exists(path):
        os.remove(path)
        return True
    return False
