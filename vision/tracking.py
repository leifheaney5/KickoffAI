#!/usr/bin/env python3
"""Kickoff Pulse — identity permanence (re-identification).

Ultralytics' BoT-SORT / ByteTrack give us short-term track ids, but they still
mint a *brand new* id whenever a player is lost for too long (a hard occlusion,
a player running off-screen during a camera pan, a missed detection streak).

This module sits on top of the base tracker and stitches those fragments back
together. It maintains the last-known position and velocity of every identity
and, when an unfamiliar raw id appears, tries to reclaim a recently-lost
identity whose *predicted* position is close enough (a constant-velocity motion
gate). The result is a stable "canonical id" per real-world player.

The algorithm is deliberately framework-free (NumPy only) and coordinate-system
agnostic — feed it whatever 2D space you trust most. The pipeline feeds it
normalised pitch coordinates (0..100), which neutralise camera panning far
better than raw pixels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

Observation = Tuple[int, Sequence[float]]  # (raw_track_id, (x, y))


@dataclass
class _Identity:
    cid: int                 # canonical id
    xy: np.ndarray           # last observed position
    velocity: np.ndarray     # per-frame motion estimate
    last_frame: int
    hits: int = 1

    def predict(self, frame_index: int) -> np.ndarray:
        """Constant-velocity position estimate for ``frame_index``."""
        dt = max(0, frame_index - self.last_frame)
        return self.xy + self.velocity * dt


class IdentityManager:
    """Re-assigns historical ids to reappearing tracks via a motion gate."""

    def __init__(self, gate: float = 6.0, max_lost_frames: int = 45) -> None:
        self.gate = float(gate)
        self.max_lost_frames = int(max_lost_frames)
        self._identities: Dict[int, _Identity] = {}
        self._remap: Dict[int, int] = {}          # raw id -> canonical id
        self._next_cid = 1

    # ------------------------------------------------------------------ #
    def update(
        self, frame_index: int, observations: Sequence[Observation]
    ) -> Dict[int, int]:
        """Resolve this frame's raw ids to stable canonical ids.

        Returns a ``{raw_id: canonical_id}`` map for the supplied observations.
        """
        resolved: Dict[int, int] = {}
        claimed: set = set()
        pending: List[Observation] = []

        # Pass 1: raw ids we already know keep their canonical id.
        for raw_id, point in observations:
            xy = np.asarray(point, dtype=float)
            cid = self._remap.get(raw_id)
            if cid is not None and cid in self._identities:
                self._touch(cid, xy, frame_index)
                resolved[raw_id] = cid
                claimed.add(cid)
            else:
                pending.append((raw_id, xy))

        # Pass 2: unfamiliar raw ids try to reclaim a recently-lost identity,
        # otherwise they spawn a fresh one.
        for raw_id, xy in pending:
            cid = self._match_lost(xy, frame_index, claimed)
            if cid is None:
                cid = self._spawn(xy, frame_index)
            else:
                self._touch(cid, xy, frame_index)
            self._remap[raw_id] = cid
            resolved[raw_id] = cid
            claimed.add(cid)

        self._prune(frame_index)
        return resolved

    # ------------------------------------------------------------------ #
    def _match_lost(
        self, xy: np.ndarray, frame_index: int, claimed: set
    ) -> Optional[int]:
        """Find the closest dormant identity within the motion gate."""
        best_cid: Optional[int] = None
        best_dist = self.gate
        for cid, ident in self._identities.items():
            if cid in claimed:
                continue
            age = frame_index - ident.last_frame
            if age <= 0 or age > self.max_lost_frames:
                continue
            dist = float(np.linalg.norm(ident.predict(frame_index) - xy))
            if dist <= best_dist:
                best_dist = dist
                best_cid = cid
        return best_cid

    def _spawn(self, xy: np.ndarray, frame_index: int) -> int:
        cid = self._next_cid
        self._next_cid += 1
        self._identities[cid] = _Identity(
            cid=cid, xy=xy, velocity=np.zeros(2), last_frame=frame_index
        )
        return cid

    def _touch(self, cid: int, xy: np.ndarray, frame_index: int) -> None:
        ident = self._identities[cid]
        dt = max(1, frame_index - ident.last_frame)
        measured_v = (xy - ident.xy) / dt
        # Exponential smoothing keeps the velocity estimate stable.
        ident.velocity = 0.5 * ident.velocity + 0.5 * measured_v
        ident.xy = xy
        ident.last_frame = frame_index
        ident.hits += 1

    def _prune(self, frame_index: int) -> None:
        """Forget identities lost for longer than the re-ID window."""
        dead = [
            cid
            for cid, ident in self._identities.items()
            if frame_index - ident.last_frame > self.max_lost_frames
        ]
        for cid in dead:
            del self._identities[cid]
        # Drop stale raw->canonical entries pointing at forgotten identities.
        self._remap = {
            raw: cid for raw, cid in self._remap.items() if cid in self._identities
        }

    # ------------------------------------------------------------------ #
    @property
    def active_count(self) -> int:
        return len(self._identities)
