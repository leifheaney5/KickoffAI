#!/usr/bin/env python3
"""Kickoff Pulse — pitch homography.

Translate raw screen pixel coordinates into a top-down tactical pitch frame.

Two coordinate systems are produced:

* **Metres** — a real-world plane the size of the pitch (default 105 x 68 m).
  Distances here are physically meaningful, which is what the possession /
  passing heuristics need (e.g. the 1.5 m possession radius).
* **Normalised 0..100** — the schema's tactical coordinates, derived by simply
  scaling metres onto a 0..100 box on each axis.

The transform is built from four user-supplied ground-truth points (corner
flags, penalty-box intersections, ...) via ``cv2.getPerspectiveTransform`` and
applied with ``cv2.perspectiveTransform``.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import numpy as np

PointsLike = Sequence[Sequence[float]]


class PitchHomography:
    """A 4-point perspective map from image pixels to pitch coordinates."""

    def __init__(
        self,
        image_points: PointsLike,
        pitch_points_m: Optional[PointsLike] = None,
        pitch_length_m: float = 105.0,
        pitch_width_m: float = 68.0,
    ) -> None:
        """
        Parameters
        ----------
        image_points:
            Four ``(x, y)`` pixel coordinates of known pitch landmarks, in a
            consistent order (e.g. TL, TR, BR, BL corner flags).
        pitch_points_m:
            The same four landmarks expressed in pitch metres. Defaults to the
            four pitch corners ``(0,0) (L,0) (L,W) (0,W)`` — i.e. ``image_points``
            are assumed to be those corners in the same order.
        pitch_length_m, pitch_width_m:
            Real pitch dimensions, used for the default corners and for the
            metres -> 0..100 normalisation.
        """
        # Lazy import keeps `numpy`-only consumers from needing OpenCV.
        import cv2

        self.pitch_length_m = float(pitch_length_m)
        self.pitch_width_m = float(pitch_width_m)

        src = np.asarray(image_points, dtype=np.float32)
        if src.shape != (4, 2):
            raise ValueError(
                f"image_points must be 4x2, got {src.shape}; "
                "supply exactly four (x, y) reference points."
            )

        if pitch_points_m is None:
            dst = np.array(
                [
                    [0.0, 0.0],
                    [self.pitch_length_m, 0.0],
                    [self.pitch_length_m, self.pitch_width_m],
                    [0.0, self.pitch_width_m],
                ],
                dtype=np.float32,
            )
        else:
            dst = np.asarray(pitch_points_m, dtype=np.float32)
            if dst.shape != (4, 2):
                raise ValueError(f"pitch_points_m must be 4x2, got {dst.shape}")

        self._matrix = cv2.getPerspectiveTransform(src, dst)

    # ------------------------------------------------------------------ #
    @classmethod
    def from_normalised_points(
        cls,
        image_points: PointsLike,
        pitch_points_norm: PointsLike,
        pitch_length_m: float = 105.0,
        pitch_width_m: float = 68.0,
    ) -> "PitchHomography":
        """Build from landmarks given in 0..100 units instead of metres."""
        pts = np.asarray(pitch_points_norm, dtype=np.float32)
        metres = np.column_stack(
            [pts[:, 0] / 100.0 * pitch_length_m, pts[:, 1] / 100.0 * pitch_width_m]
        )
        return cls(image_points, metres, pitch_length_m, pitch_width_m)

    # ------------------------------------------------------------------ #
    @classmethod
    def from_correspondences(
        cls,
        image_points: PointsLike,
        pitch_points_m: PointsLike,
        pitch_length_m: float = 105.0,
        pitch_width_m: float = 68.0,
    ) -> "PitchHomography":
        """Build from N>=4 point correspondences via ``cv2.findHomography``.

        Unlike the 4-point constructor, this accepts any number of matched
        points (e.g. however many pitch keypoints a detector found this frame)
        and is robust to outliers via RANSAC. Used for per-frame homography on
        panning cameras.
        """
        import cv2

        src = np.asarray(image_points, dtype=np.float32)
        dst = np.asarray(pitch_points_m, dtype=np.float32)
        if src.shape[0] < 4 or src.shape != dst.shape or src.shape[1] != 2:
            raise ValueError(
                f"need >=4 matched 2D points, got src={src.shape} dst={dst.shape}"
            )
        matrix, _ = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        if matrix is None:
            raise ValueError("findHomography failed to find a transform")

        obj = cls.__new__(cls)            # bypass the 4-point __init__
        obj.pitch_length_m = float(pitch_length_m)
        obj.pitch_width_m = float(pitch_width_m)
        obj._matrix = matrix.astype(np.float32)
        return obj

    # ------------------------------------------------------------------ #
    @property
    def matrix(self) -> np.ndarray:
        """The 3x3 perspective transform matrix (image px -> pitch metres)."""
        return self._matrix

    def to_metres(self, points_px: PointsLike) -> np.ndarray:
        """Map ``(N, 2)`` pixel coordinates to pitch metres."""
        import cv2

        pts = np.asarray(points_px, dtype=np.float32).reshape(-1, 1, 2)
        out = cv2.perspectiveTransform(pts, self._matrix)
        return out.reshape(-1, 2)

    def metres_to_normalised(self, points_m: PointsLike) -> np.ndarray:
        """Scale pitch metres onto the 0..100 tactical box."""
        pts = np.asarray(points_m, dtype=np.float32).reshape(-1, 2)
        return np.column_stack(
            [
                pts[:, 0] / self.pitch_length_m * 100.0,
                pts[:, 1] / self.pitch_width_m * 100.0,
            ]
        )

    def to_normalised(self, points_px: PointsLike) -> np.ndarray:
        """Map ``(N, 2)`` pixel coordinates straight to 0..100 coordinates."""
        return self.metres_to_normalised(self.to_metres(points_px))

    @staticmethod
    def is_inside(point_norm: Sequence[float], margin: float = 0.0) -> bool:
        """True if a normalised point lies on the pitch (within ``margin``)."""
        x, y = point_norm[0], point_norm[1]
        return (-margin <= x <= 100 + margin) and (-margin <= y <= 100 + margin)


def fallback_normalised(
    points_px: PointsLike, frame_width: int, frame_height: int
) -> np.ndarray:
    """Naive image-space normalisation used when no homography is provided.

    Simply scales pixel coordinates into 0..100 of the frame. This is *not* a
    true tactical projection (it keeps the camera's perspective), but it lets
    the pipeline run and produce coherent relative positions for a quick look.
    """
    pts = np.asarray(points_px, dtype=np.float32).reshape(-1, 2)
    w = max(1, frame_width)
    h = max(1, frame_height)
    return np.column_stack([pts[:, 0] / w * 100.0, pts[:, 1] / h * 100.0])
