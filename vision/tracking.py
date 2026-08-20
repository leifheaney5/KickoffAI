#!/usr/bin/env python3
"""Kickoff Pulse — identity permanence (re-identification).

Ultralytics' BoT-SORT / ByteTrack give us short-term track ids, but they still
mint a *brand new* id whenever a player is lost for too long (a hard occlusion,
a player running off-screen during a camera pan, a missed detection streak).

This module sits on top of the base tracker and stitches those fragments back
together. It maintains the last-known position and velocity of every identity
and, when an unfamiliar raw id appears, tries to reclaim a recently-lost
identity whose predicted position is close enough. The result is a stable
"canonical id" per real-world player.

Three things about that gate are easy to get wrong, and the first version of
this module got all three wrong. Measured on the synthetic replay in
tests/test_tracking.py. That replay is calibrated against three real 10-minute
runs of the same match at rising detection quality, which produced 936, 1093
and 1327 distinct tracks for 22 players — 0.010 to 0.013 canonical ids per
detection. The replay runs harder than that, at 0.018 to 0.027, so what it
measures is a conservative reading of the real thing:

* **The gate has to widen with the gap.** A single fixed radius is simultaneously
  too generous at a one-frame gap — where it pulls in half the players around
  the ball and lets nearest-neighbour pick the wrong one — and far too mean at a
  ten-frame gap, where the player has genuinely had a second to run. Fixing only
  this took canonical ids from 176 to 66 on the arm-C replay.

* **Velocity extrapolation past a few frames is noise amplification.** The
  estimate is a difference of two noisy positions; multiplying it by the gap
  drives the prediction off the pitch. Straight-line extrapolation was measurably
  *worse than holding the last position* at every gap length beyond one frame.

* **A frame has to be solved as a whole.** Handing each observation its nearest
  free identity in whatever order the detector emitted boxes mis-assigns under
  crowding, and the mis-assignment cascades: the rightful owner finds its
  identity taken and spawns a new one.

The algorithm is deliberately framework-free (NumPy only) and coordinate-system
agnostic — feed it whatever 2D space you trust most. The pipeline feeds it
normalised pitch coordinates (0..100), which neutralise camera panning far
better than raw pixels. Every distance constant below is in those units, so
they are resolution-independent: 1 unit is 1.05 m along the pitch and 0.68 m
across it.

What this module cannot do is tell two players apart when both are plausible.
It sees positions and nothing else — the team-colour classifier and the jersey
OCR both run *downstream* of it, keyed by the canonical ids it produces. Giving
re-ID a team or kit-colour signal to gate on is the single biggest improvement
available here, and it needs a pipeline change, not a change in this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

Observation = Tuple[int, Sequence[float]]  # (raw_track_id, (x, y))


@dataclass
class IdentityStats:
    """Why the re-ID layer made the identities it made.

    Fragmentation is only diagnosable if you can tell *which* failure produced
    each surplus id. A spawn with no dormant candidate at all is a real newcomer
    (or someone whose identity genuinely expired); a spawn with candidates that
    all sat outside the gate is a gate that is too tight; a spawn that had an
    in-gate candidate and lost it to a closer claim is an assignment problem,
    which is a different fix. On the real footage the counts said gate, loudly.
    """

    frames: int = 0
    observations: int = 0
    spawns: int = 0            # new canonical ids minted
    reclaims: int = 0          # dormant identities stitched back on
    gate_misses: int = 0       # spawned, but a dormant candidate was in window
    claim_blocks: int = 0      # spawned; nearest in-gate candidate already taken
    expiries: int = 0          # identities dropped for exceeding the window

    def as_dict(self) -> Dict[str, float]:
        """Flat summary, plus the two ratios that actually mean something."""
        per_det = self.spawns / self.observations if self.observations else 0.0
        per_frame = self.observations / self.frames if self.frames else 0.0
        return {
            "frames": self.frames,
            "observations": self.observations,
            "spawns": self.spawns,
            "reclaims": self.reclaims,
            "gate_misses": self.gate_misses,
            "claim_blocks": self.claim_blocks,
            "expiries": self.expiries,
            "ids_per_detection": per_det,
            "observations_per_frame": per_frame,
        }


# A player covers at most ~0.8 m in one sampled frame (8 m/s at 10 fps, which
# is stride 3 on 30 fps source). On a 105 x 68 m pitch mapped to 0..100 that is
# 0.76 units along the length or 1.18 across the width, so 1.2 units bounds any
# honest single-frame step. Anything faster is a homography error or a swapped
# box, and must not be fed into the motion model as if it were running.
MAX_STEP = 1.2

# How far ahead a velocity estimate is worth trusting. The estimate is a
# difference of two noisy positions, so its error is roughly the position error
# itself and extrapolating multiplies that error by the gap while the player is
# busy turning, stopping and changing direction. Measured on the synthetic
# replay, straight-line extrapolation is worse than simply holding the last
# position at *every* gap length beyond one frame — median miss 5.8 units
# against 3.7 at a 4-6 frame gap, 9.4 against 5.9 at 7-15. Three frames (0.3 s)
# is where coasting still pays for itself.
COAST_FRAMES = 3

# The gate never opens wider than this, however long the gap. Twenty normalised
# units is about 21 m along the pitch or 14 m across it, roughly 1.7 s of
# sprinting; past that a "match" is a guess, and a wrong match costs more than a
# fresh identity because it corrupts two players at once.
GATE_MAX = 20.0

# How much of the newest measurement enters the velocity estimate. Lower than
# the obvious 0.5 because single-frame differences are mostly noise here.
VELOCITY_ALPHA = 0.3


@dataclass
class _Identity:
    cid: int                 # canonical id
    xy: np.ndarray           # last observed position
    velocity: np.ndarray     # per-frame motion estimate
    last_frame: int
    hits: int = 1

    def predict(self, frame_index: int) -> np.ndarray:
        """Where this identity plausibly is at ``frame_index``.

        Constant velocity for the first few frames of a gap, then frozen. See
        COAST_FRAMES: past that horizon the extrapolation is noise amplification
        dressed up as physics, and the last observed position is a better guess.
        """
        dt = max(0, frame_index - self.last_frame)
        return self.xy + self.velocity * min(dt, COAST_FRAMES)


class IdentityManager:
    """Re-assigns historical ids to reappearing tracks via a motion gate."""

    def __init__(self, gate: float = 6.0, max_lost_frames: int = 45) -> None:
        self.gate = float(gate)
        self.max_lost_frames = int(max_lost_frames)
        self._identities: Dict[int, _Identity] = {}
        self._remap: Dict[int, int] = {}          # raw id -> canonical id
        self._next_cid = 1
        self.stats = IdentityStats()

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
        self.stats.frames += 1
        self.stats.observations += len(observations)

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
        # otherwise they spawn a fresh one. Resolved for the frame as a whole
        # rather than one observation at a time — see _assign_lost.
        candidates = self._candidates(frame_index, claimed)
        matched, contested = self._assign_lost(pending, candidates)
        for raw_id, xy in pending:
            cid = matched.get(raw_id)
            if cid is None:
                cid = self._spawn(xy, frame_index)
                if raw_id in contested:
                    self.stats.claim_blocks += 1
                elif candidates:
                    self.stats.gate_misses += 1
            else:
                self._touch(cid, xy, frame_index)
                self.stats.reclaims += 1
            self._remap[raw_id] = cid
            resolved[raw_id] = cid
            claimed.add(cid)

        self._prune(frame_index)
        return resolved

    # ------------------------------------------------------------------ #
    def gate_for(self, gap: int) -> float:
        """How far an identity may have travelled during a ``gap``-frame absence.

        A single fixed radius is wrong at both ends. At a one-frame gap it is far
        too generous — a player moves at most ~1.2 units, so a 6-unit radius pulls
        in half the players around the ball and nearest-neighbour picks whichever
        of them happens to be closest. At a ten-frame gap it is far too mean —
        the player has genuinely had a second to run and is routinely 10 units
        away, so the true owner is excluded and a new identity is minted.

        The radius therefore grows with the gap: the fixed part is the
        measurement-error budget (bbox foot point plus homography, which is what
        the caller's ``gate`` sets), and it opens by one sprint-step for every
        frame the identity has been missing, up to GATE_MAX.
        """
        return min(self.gate + MAX_STEP * max(0, gap - 1), GATE_MAX)

    def _candidates(
        self, frame_index: int, claimed: set
    ) -> List[Tuple[int, np.ndarray, float]]:
        """Dormant identities still inside the re-ID window, with their gates."""
        out = []
        for cid, ident in self._identities.items():
            if cid in claimed:
                continue
            gap = frame_index - ident.last_frame
            if gap <= 0 or gap > self.max_lost_frames:
                continue
            out.append((cid, ident.predict(frame_index), self.gate_for(gap)))
        return out

    def _assign_lost(
        self,
        pending: Sequence[Observation],
        candidates: Sequence[Tuple[int, np.ndarray, float]],
    ) -> Tuple[Dict[int, int], set]:
        """Match this frame's unfamiliar raw ids to dormant identities at once.

        Taking each observation in turn and handing it its nearest free identity
        makes the result depend on detection order, which is arbitrary. In a
        crowd that is not a cosmetic problem: the first observation offered
        takes an identity that belonged to someone standing slightly further
        away, the rightful owner then finds it gone and spawns, and the error
        propagates. On the synthetic replay this mis-assigned roughly four in
        ten reclaims even where the true owner was the obvious candidate.

        So every admissible (observation, identity) pair is costed and the pairs
        are committed cheapest-first across the whole frame. That is not the
        Hungarian optimum, but it is order-independent and, with the gate
        keeping the matrix sparse, measured within a couple of identities of it.

        Returns the matches, and the raw ids that had an admissible identity but
        lost it to a closer claim — those are the spawns an assignment change
        could still recover, as opposed to the ones that had nothing to match.
        """
        if not candidates or not pending:
            return {}, set()
        pairs = []
        for raw_id, xy in pending:
            for cid, predicted, gate in candidates:
                dist = float(np.linalg.norm(predicted - xy))
                if dist <= gate:
                    pairs.append((dist, raw_id, cid))
        # Ties broken on raw then canonical id so a frame always resolves the
        # same way, whatever order the detector happened to emit boxes in.
        pairs.sort()
        taken_raw: set = set()
        taken_cid: set = set()
        matched: Dict[int, int] = {}
        for _, raw_id, cid in pairs:
            if raw_id in taken_raw or cid in taken_cid:
                continue
            taken_raw.add(raw_id)
            taken_cid.add(cid)
            matched[raw_id] = cid
        contested = {raw_id for _, raw_id, _ in pairs} - taken_raw
        return matched, contested

    def _spawn(self, xy: np.ndarray, frame_index: int) -> int:
        cid = self._next_cid
        self._next_cid += 1
        self.stats.spawns += 1
        self._identities[cid] = _Identity(
            cid=cid, xy=xy, velocity=np.zeros(2), last_frame=frame_index
        )
        return cid

    def _touch(self, cid: int, xy: np.ndarray, frame_index: int) -> None:
        ident = self._identities[cid]
        dt = max(1, frame_index - ident.last_frame)
        measured_v = (xy - ident.xy) / dt
        speed = float(np.linalg.norm(measured_v))
        if speed > MAX_STEP:
            # Nobody covers that much ground in a tenth of a second. Whatever
            # produced it — a homography that jumped, a box that snapped to the
            # wrong player — it is not motion, so clip it rather than let it
            # steer the next prediction off the pitch.
            measured_v *= MAX_STEP / speed
        # Exponential smoothing keeps the velocity estimate stable.
        ident.velocity = (1.0 - VELOCITY_ALPHA) * ident.velocity + (
            VELOCITY_ALPHA * measured_v
        )
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
        self.stats.expiries += len(dead)
        # Drop stale raw->canonical entries pointing at forgotten identities.
        self._remap = {
            raw: cid for raw, cid in self._remap.items() if cid in self._identities
        }

    # ------------------------------------------------------------------ #
    @property
    def active_count(self) -> int:
        return len(self._identities)

    @property
    def total_identities(self) -> int:
        """Canonical ids minted over the whole run, expired ones included."""
        return self._next_cid - 1

    def summary(self) -> Dict[str, float]:
        """Instrumentation the caller can log next to the run's other counters."""
        out = self.stats.as_dict()
        out["total_identities"] = self.total_identities
        out["active_identities"] = self.active_count
        return out
