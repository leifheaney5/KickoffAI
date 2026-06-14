#!/usr/bin/env python3
"""Kickoff Pulse — jersey OCR + team colour classification.

Two cooperating pieces of "who is this player" logic:

* :class:`JerseyOCR` reads a shirt number from a player crop with a lightweight
  local OCR engine (EasyOCR by default).
* :class:`TeamClassifier` clusters torso colours in HSV space with K-Means to
  split outfield players into Home vs Away, and stabilises the per-track vote.

Both lazy-import their heavy backends (EasyOCR, scikit-learn, OpenCV) so the
rest of the package stays importable on a machine without them.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .config import PipelineConfig
from .detection import BBox


# --------------------------------------------------------------------------- #
def torso_patch(frame: np.ndarray, box: BBox) -> Optional[np.ndarray]:
    """Crop the shirt region of a player box (upper-central torso).

    Excludes the head, arms and legs to keep the dominant colour on the jersey
    rather than skin, shorts or grass.
    """
    x1, y1, x2, y2 = box
    h = y2 - y1
    w = x2 - x1
    if h <= 1 or w <= 1:
        return None
    # Vertical 15%..50% (chest/back), horizontal central 60%.
    ty1 = int(y1 + 0.15 * h)
    ty2 = int(y1 + 0.50 * h)
    tx1 = int(x1 + 0.20 * w)
    tx2 = int(x1 + 0.80 * w)
    ty1, ty2 = max(0, ty1), min(frame.shape[0], ty2)
    tx1, tx2 = max(0, tx1), min(frame.shape[1], tx2)
    if ty2 <= ty1 or tx2 <= tx1:
        return None
    return frame[ty1:ty2, tx1:tx2]


# --------------------------------------------------------------------------- #
class JerseyOCR:
    """Reads shirt numbers (0..99) from player crops via EasyOCR."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self._reader = None

    def _ensure_reader(self):
        if self._reader is None:
            try:
                import easyocr
            except ImportError as exc:  # pragma: no cover - dependency guard
                raise ImportError(
                    "EasyOCR is required for jersey OCR. Install the vision "
                    "extras: pip install -r vision/requirements.txt "
                    "(or disable with ocr_enabled=False)."
                ) from exc
            self._reader = easyocr.Reader(["en"], gpu=self.config.use_gpu_ocr)
        return self._reader

    def read_number(self, crop: np.ndarray) -> Optional[Tuple[int, float]]:
        """Return ``(number, confidence)`` or ``None`` if no digits are read."""
        if crop is None or crop.size == 0:
            return None
        reader = self._ensure_reader()
        # allowlist restricts the recogniser to digits -> far fewer false reads.
        results = reader.readtext(crop, allowlist="0123456789", detail=1)
        best: Optional[Tuple[int, float]] = None
        for _box, text, conf in results:
            text = text.strip()
            if not text.isdigit():
                continue
            number = int(text)
            if not (0 <= number <= 99):
                continue
            if conf < self.config.ocr_min_conf:
                continue
            if best is None or conf > best[1]:
                best = (number, float(conf))
        return best


# --------------------------------------------------------------------------- #
class TeamClassifier:
    """K-Means over torso HSV colour to split players into Home / Away."""

    _MAX_GLOBAL = 2000        # cap fitting pool to bound memory / time
    _MAX_PER_TRACK = 25       # recent colour memory per canonical id

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self._global: List[np.ndarray] = []
        self._per_track: Dict[int, List[np.ndarray]] = {}
        self._centroids: Optional[np.ndarray] = None  # (2, 4)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _feature(crop: np.ndarray) -> Optional[np.ndarray]:
        """A hue-aware 4-vector ``[cos(h), sin(h), saturation, value]``.

        Hue is encoded on the unit circle so that the 0/180 wrap-around does not
        fool the Euclidean distance K-Means relies on.
        """
        import cv2

        if crop is None or crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        h = hsv[:, :, 0].astype(np.float32)
        s = hsv[:, :, 1].astype(np.float32)
        v = hsv[:, :, 2].astype(np.float32)
        # Drop grass/shadow/glare so the shirt colour dominates.
        mask = (s > 40) & (v > 40) & (v < 250)
        if mask.sum() < 0.05 * mask.size:
            mask = np.ones_like(mask, dtype=bool)
        hue_rad = np.deg2rad(h[mask] * 2.0)        # OpenCV hue is 0..179
        return np.array(
            [
                float(np.cos(hue_rad).mean()),
                float(np.sin(hue_rad).mean()),
                float(s[mask].mean() / 255.0),
                float(v[mask].mean() / 255.0),
            ],
            dtype=np.float32,
        )

    # ------------------------------------------------------------------ #
    def observe(self, cid: int, crop: np.ndarray) -> None:
        """Record a torso colour sample for canonical id ``cid``."""
        feat = self._feature(crop)
        if feat is None:
            return
        self._global.append(feat)
        if len(self._global) > self._MAX_GLOBAL:
            self._global.pop(0)
        bucket = self._per_track.setdefault(cid, [])
        bucket.append(feat)
        if len(bucket) > self._MAX_PER_TRACK:
            bucket.pop(0)
        self._maybe_fit()

    def _maybe_fit(self) -> None:
        if self._centroids is not None:
            # Periodically refit as more colour evidence accumulates.
            if len(self._global) % 50 != 0:
                return
        elif len(self._global) < self.config.team_fit_min_samples:
            return
        try:
            from sklearn.cluster import KMeans
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ImportError(
                "scikit-learn is required for team classification. Install the "
                "vision extras: pip install -r vision/requirements.txt"
            ) from exc
        data = np.vstack(self._global)
        model = KMeans(n_clusters=2, n_init=10, random_state=0).fit(data)
        self._centroids = model.cluster_centers_.astype(np.float32)

    # ------------------------------------------------------------------ #
    def _cluster_of(self, feat: np.ndarray) -> int:
        dists = np.linalg.norm(self._centroids - feat, axis=1)
        return int(np.argmin(dists))

    def _cluster_to_team(self, cluster: int) -> str:
        home_cluster = 1 if self.config.swap_teams else 0
        return "Home" if cluster == home_cluster else "Away"

    @property
    def is_ready(self) -> bool:
        return self._centroids is not None

    def team_for(self, cid: int) -> Optional[str]:
        """Majority-vote team for a canonical id, or ``None`` until fitted.

        Voting over the track's recent colour history (rather than a single
        frame) shrugs off motion blur and the odd mis-cropped frame.
        """
        if self._centroids is None:
            return None
        feats = self._per_track.get(cid)
        if not feats:
            return None
        votes = {"Home": 0, "Away": 0}
        for feat in feats:
            votes[self._cluster_to_team(self._cluster_of(feat))] += 1
        return "Home" if votes["Home"] >= votes["Away"] else "Away"
