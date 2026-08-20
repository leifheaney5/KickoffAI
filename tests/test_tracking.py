#!/usr/bin/env python3
"""Tests for identity permanence (vision/tracking.py).

This module had zero tests while it was quietly fragmenting 22 real players
into 936, 1093 and 1327 canonical tracks on three real runs of the same match
— and getting worse as detection improved. Two kinds of test live here:

* hand-derived unit tests for the motion gate, the expiry window, the
  constant-velocity prediction and the reclaim path, where every expected
  number is worked out on paper in the test's own docstring;
* a synthetic replay that stands in for footage CI cannot run. It moves 22
  players around a normalised pitch and then degrades them the way the real
  pipeline does: missed detections in bursts, occlusion, per-frame homography
  wobble, and a base tracker that re-mints and swaps its own raw ids under
  crowding. The invariant is that IdentityManager collapses that mess back
  toward 22.

Coordinates are the pipeline's normalised pitch units (0..100 on both axes) at
the sampled frame rate (stride 3 of 30 fps, so ~10 frames per second).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pytest

from vision.tracking import (
    GATE_MAX,
    MAX_STEP,
    IdentityManager,
    IdentityStats,
    _Identity,
)


# --------------------------------------------------------------------------- #
# Units used throughout.
#
# The pitch is 105 x 68 m mapped onto 0..100 on both axes, so one normalised
# unit is 1.05 m along the length and 0.68 m across the width. At 10 sampled
# frames per second an 8 m/s sprint moves a player 0.8 m per frame, which is
# 0.76 units along x or 1.18 units across y. Nothing legitimate exceeds ~1.2
# units of displacement in a single sampled frame.
SPRINT_STEP = 1.2

PLAYERS = 22


# --------------------------------------------------------------------------- #
# Unit tests: the motion gate
# --------------------------------------------------------------------------- #

def test_known_raw_id_keeps_its_identity():
    """The cheap path: a raw id the base tracker holds on to never re-IDs."""
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    first = mgr.update(0, [(7, (10.0, 10.0))])
    second = mgr.update(1, [(7, (10.5, 10.0))])
    assert first[7] == second[7]
    assert mgr.stats.spawns == 1
    assert mgr.stats.reclaims == 0


def test_gate_accepts_a_plausible_reappearance():
    """A player lost for one frame reappears one sprint-step further on.

    Raw id 1 walks +1.0 unit in x per frame for four frames, so its velocity
    estimate settles near (1.0, 0). Frame 4 misses it entirely and a fresh raw
    id appears on frame 5 at x = 15.0 — exactly where a constant-velocity
    player would be after two more frames. That must reclaim, not spawn.
    """
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    for f in range(4):
        cid_map = mgr.update(f, [(1, (10.0 + f, 20.0))])
    original = cid_map[1]
    mgr.update(4, [])                       # detection missed
    resolved = mgr.update(5, [(99, (15.0, 20.0))])
    assert resolved[99] == original
    assert mgr.stats.reclaims == 1
    assert mgr.stats.spawns == 1            # only the original


def test_gate_rejects_an_implausible_reappearance():
    """Half a pitch away in one frame is not the same player.

    Raw id 1 sits still at (10, 20). A new raw id shows up at (60, 20) on the
    next frame: 50 normalised units, about 52 m, in a tenth of a second. Any
    gate that lets that through is not a motion gate.
    """
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    mgr.update(0, [(1, (10.0, 20.0))])
    mgr.update(1, [(1, (10.0, 20.0))])
    resolved = mgr.update(2, [(2, (60.0, 20.0))])
    assert resolved[2] != 1
    assert mgr.stats.spawns == 2
    assert mgr.stats.gate_misses == 1


def test_constant_velocity_prediction_is_linear_over_short_gaps():
    """predict() is position + velocity * frames elapsed, then it stops.

    Velocity (0.5, -0.25) from (10, 20) at frame 100. One frame on that is
    (10.5, 19.75); three frames on, (11.5, 19.25). Past the three-frame coasting
    horizon the answer stays (11.5, 19.25) however long the gap gets, because
    the estimate has stopped being worth extrapolating.
    """
    ident = _Identity(
        cid=1, xy=np.array([10.0, 20.0]), velocity=np.array([0.5, -0.25]),
        last_frame=100,
    )
    assert ident.predict(100) == pytest.approx([10.0, 20.0])
    assert ident.predict(101) == pytest.approx([10.5, 19.75])
    assert ident.predict(103) == pytest.approx([11.5, 19.25])
    assert ident.predict(110) == pytest.approx([11.5, 19.25])
    assert ident.predict(145) == pytest.approx([11.5, 19.25])
    # Asking about the past must not run the model backwards.
    assert ident.predict(96) == pytest.approx([10.0, 20.0])


def test_gate_opens_by_one_sprint_step_per_missing_frame():
    """Hand-computed: 6.0 base, plus 1.2 per frame of gap, capped at 20.

    gap 1 is the caller's gate untouched (6.0), because a player who was here
    last frame is still here. gap 2 adds one sprint step (7.2), gap 6 adds five
    (12.0), and gap 45 would want 6 + 1.2 * 44 = 58.8 — most of the pitch — so
    the cap takes over well before then.
    """
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    assert mgr.gate_for(1) == pytest.approx(6.0)
    assert mgr.gate_for(2) == pytest.approx(7.2)
    assert mgr.gate_for(6) == pytest.approx(12.0)
    assert mgr.gate_for(12) == pytest.approx(19.2)
    assert mgr.gate_for(13) == pytest.approx(GATE_MAX)
    assert mgr.gate_for(45) == pytest.approx(GATE_MAX)


def test_velocity_trusts_history_more_than_the_newest_frame():
    """One frame's displacement is mostly measurement noise, not motion.

    A single-frame difference of two noisy positions has roughly the position
    error in it, so letting the newest frame move the estimate half way — the
    obvious 0.5 split — makes the estimate track the jitter. It weights history
    0.7 to 0.3 instead: a player stepping a steady 1.0 unit per frame reads
    0.3 after one observation and 0.7 * 0.3 + 0.3 = 0.51 after two, rather than
    the 0.5 and 0.75 an even split would give. On the replay the even split
    costs about three points of identity quality.
    """
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    resolved = mgr.update(0, [(1, (10.0, 50.0))])
    ident = mgr._identities[resolved[1]]
    mgr.update(1, [(1, (11.0, 50.0))])
    assert ident.velocity == pytest.approx([0.3, 0.0])
    mgr.update(2, [(1, (12.0, 50.0))])
    assert ident.velocity == pytest.approx([0.51, 0.0])


def test_a_teleporting_observation_cannot_poison_the_velocity_estimate():
    """A 40-unit jump is a bad homography or a swapped box, not a sprint.

    Left unclipped it becomes a 40-unit-per-frame velocity, and the identity's
    next prediction lands off the pitch where nothing will ever match it. The
    measured velocity is clipped to one sprint step before it is smoothed in,
    so the identity's speed can never exceed MAX_STEP.
    """
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    resolved = mgr.update(0, [(1, (10.0, 10.0))])
    mgr.update(1, [(1, (50.0, 10.0))])
    ident = mgr._identities[resolved[1]]
    assert float(np.linalg.norm(ident.velocity)) <= MAX_STEP


def test_prediction_does_not_extrapolate_a_player_off_the_pitch():
    """A long gap must not turn a velocity estimate into a wild guess.

    A player last seen at (50, 50) with a 1.0 unit-per-frame estimate would,
    under straight-line extrapolation, be predicted 45 units away after 45
    sampled frames — half a pitch, and nobody runs 47 m without turning. A
    prediction that far from the truth guarantees the gate misses and the
    player spawns a new identity. The extrapolation has to stop.
    """
    ident = _Identity(
        cid=1, xy=np.array([50.0, 50.0]), velocity=np.array([1.0, 0.0]),
        last_frame=0,
    )
    drift = float(np.linalg.norm(ident.predict(45) - ident.xy))
    assert drift <= 10.0


# --------------------------------------------------------------------------- #
# Unit tests: expiry and reclaim
# --------------------------------------------------------------------------- #

def test_identity_expires_after_max_lost_frames():
    """One frame past the window the identity is gone and cannot be reclaimed."""
    mgr = IdentityManager(gate=6.0, max_lost_frames=5)
    mgr.update(0, [(1, (30.0, 30.0))])
    assert mgr.active_count == 1
    mgr.update(5, [])                       # age 5, still inside the window
    assert mgr.active_count == 1
    mgr.update(6, [])                       # age 6, one past it
    assert mgr.active_count == 0
    assert mgr.stats.expiries == 1
    # Standing exactly where it vanished no longer buys anything.
    resolved = mgr.update(7, [(2, (30.0, 30.0))])
    assert resolved[2] == 2                 # a brand-new canonical id
    assert mgr.stats.reclaims == 0


def test_reclaim_after_an_occlusion():
    """Behind a defender for a second, out the other side, same identity.

    Ten frames of tracking at +0.4 units per frame ending at x = 23.6, then
    eight frames hidden (0.8 s), then a new raw id at 23.6 + 8 * 0.4 = 26.8,
    the position the player would have reached. Eight frames is well inside a
    45-frame window and the reappearance is a plausible continuation, so this
    is one identity, not two.
    """
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    for f in range(10):
        cid_map = mgr.update(f, [(4, (20.0 + 0.4 * f, 40.0))])
    original = cid_map[4]
    for f in range(10, 18):
        mgr.update(f, [])
    resolved = mgr.update(18, [(77, (26.8, 40.0))])
    assert resolved[77] == original
    assert mgr.stats.spawns == 1


def test_stale_raw_ids_do_not_resurrect_a_dead_identity():
    """A raw id the base tracker recycles must not inherit an expired identity."""
    mgr = IdentityManager(gate=6.0, max_lost_frames=3)
    mgr.update(0, [(1, (10.0, 10.0))])
    for f in range(1, 6):
        mgr.update(f, [])
    assert mgr.active_count == 0
    resolved = mgr.update(6, [(1, (10.0, 10.0))])
    assert resolved[1] != 1


def test_an_identity_seen_this_frame_cannot_also_be_reclaimed():
    """Two live raw ids are two players, however close together they stand.

    Duplicate boxes on the same person are a detection bug; merging them here
    would hide it and, worse, let one player answer for two.
    """
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    mgr.update(0, [(1, (50.0, 50.0))])
    resolved = mgr.update(1, [(1, (50.0, 50.0)), (2, (50.2, 50.0))])
    assert resolved[1] != resolved[2]


def test_crowded_frame_does_not_let_one_player_take_another_identity():
    """Global assignment, not first-come-first-served.

    Two players stand 3 units apart at (40, 50) and (43, 50), both stationary,
    and both go missing for a frame. They come back as new raw ids, with the
    frame ordered so the *right-hand* observation is offered first. Taking each
    pending observation in turn and giving it its nearest free identity assigns
    the right-hand player to whichever identity the dictionary offers first,
    which strands the other into a fresh spawn. Total distance decides it
    instead: 0 + 0 for the honest pairing against 3 + 3 for the crossed one.
    """
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    for f in range(3):
        cid_map = mgr.update(f, [(1, (40.0, 50.0)), (2, (43.0, 50.0))])
    left, right = cid_map[1], cid_map[2]
    mgr.update(3, [])
    resolved = mgr.update(4, [(20, (43.0, 50.0)), (10, (40.0, 50.0))])
    assert resolved[10] == left
    assert resolved[20] == right
    assert mgr.stats.spawns == 2


def test_a_contested_reclaim_is_counted_apart_from_a_gate_miss():
    """Two claimants, one identity: the loser is an assignment cost, not a gate.

    Raw id 1 holds still at (50, 50) and then vanishes. Next frame two new raw
    ids appear, at 0.5 and 2.0 units away — both inside the 6-unit one-frame
    gate. Only one identity is on offer, so the nearer takes it and the other
    spawns. That spawn is not evidence the gate is too tight, and the counters
    have to say so or the next person tuning this chases the wrong number.
    """
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    mgr.update(0, [(1, (50.0, 50.0))])
    resolved = mgr.update(1, [(2, (50.5, 50.0)), (3, (52.0, 50.0))])
    assert resolved[2] != resolved[3]
    assert mgr.stats.reclaims == 1
    assert mgr.stats.claim_blocks == 1
    assert mgr.stats.gate_misses == 0


def test_summary_exposes_the_counters_the_caller_needs():
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    mgr.update(0, [(1, (10.0, 10.0)), (2, (80.0, 80.0))])
    mgr.update(1, [(1, (10.5, 10.0))])
    out = mgr.summary()
    assert out["frames"] == 2
    assert out["observations"] == 3
    assert out["spawns"] == 2
    assert out["total_identities"] == 2
    assert out["active_identities"] == 2
    assert out["ids_per_detection"] == pytest.approx(2 / 3)


def test_stats_start_empty():
    assert IdentityStats().as_dict()["ids_per_detection"] == 0.0


# --------------------------------------------------------------------------- #
# Synthetic replay
#
# Everything below builds a fake match and pushes it through IdentityManager.
# The point is not to simulate football; it is to reproduce the four things
# that actually break re-ID on real footage:
#
#   1. players bunch around the ball, so candidates are ambiguous;
#   2. detections drop out at random and in occlusion bursts;
#   3. positions carry homography jitter, so nothing lands where predicted;
#   4. the base tracker re-mints raw ids after gaps and swaps them in crowds.
#
# Take any of those out and the problem stops being interesting.
# --------------------------------------------------------------------------- #

@dataclass
class Replay:
    """One synthetic match: per-frame observations plus the ground truth."""

    # frames[f] is a list of (raw_id, (x, y), true_player_index)
    frames: List[List[Tuple[int, Tuple[float, float], int]]]

    def observations(self, index: int) -> List[Tuple[int, Tuple[float, float]]]:
        return [(raw, xy) for raw, xy, _ in self.frames[index]]

    @property
    def raw_id_count(self) -> int:
        return len({raw for frame in self.frames for raw, _, _ in frame})

    @property
    def detections(self) -> int:
        return sum(len(frame) for frame in self.frames)


def _formation() -> np.ndarray:
    """22 starting slots: two 4-4-2 shapes facing each other."""
    lanes = [50.0, 20.0, 40.0, 60.0, 80.0, 20.0, 40.0, 60.0, 80.0, 35.0, 65.0]
    depth = [6.0, 22.0, 20.0, 20.0, 22.0, 42.0, 40.0, 40.0, 42.0, 60.0, 60.0]
    home = np.stack([np.array(depth), np.array(lanes)], axis=1)
    away = home.copy()
    away[:, 0] = 100.0 - away[:, 0]
    return np.concatenate([home, away], axis=0)


def _true_positions(
    frames: int, rng: np.random.Generator
) -> Tuple[List[np.ndarray], List[np.ndarray]]:
    """Players chase a wandering ball, lagging it, so they bunch where it is.

    Returns the per-frame player positions and the ball position, because the
    detection model below keys off distance from the ball: that is where the
    camera is pointed and where the boxes are biggest and cleanest.
    """
    slots = _formation()
    pos = slots + rng.normal(0.0, 1.5, slots.shape)
    ball = np.array([50.0, 50.0])
    ball_v = np.zeros(2)
    players: List[np.ndarray] = []
    balls: List[np.ndarray] = []
    for _ in range(frames):
        ball_v = 0.85 * ball_v + rng.normal(0.0, 1.5, 2)
        speed = float(np.linalg.norm(ball_v))
        if speed > 5.0:                     # a pass, not a teleport
            ball_v *= 5.0 / speed
        ball = np.clip(ball + ball_v, 2.0, 98.0)
        # Each player wants a point between their formation slot and the ball
        # and closes only a fraction of that gap per frame, which is what makes
        # the pack drift as a loose crowd instead of snapping onto the ball.
        target = 0.55 * slots + 0.45 * ball
        step = 0.10 * (target - pos) + rng.normal(0.0, 0.18, pos.shape)
        mag = np.linalg.norm(step, axis=1, keepdims=True)
        step *= np.minimum(1.0, SPRINT_STEP / np.maximum(mag, 1e-9))
        pos = np.clip(pos + step, 0.5, 99.5)
        players.append(pos.copy())
        balls.append(ball.copy())
    return players, balls


# How the detection recovery rate falls off away from the ball. The camera is
# pointed at the action, so players near the ball are large, sharp and quickly
# re-found after a miss; players 60 units away are small, foreshortened, often
# at the frame edge, and stay missing for longer.
BALL_FALLOFF = 70.0

# The three real pipeline arms, expressed as this simulator's detection
# quality. They were chosen to reproduce the players-per-frame those runs
# reported (15.62, 16.61 and 17.60 out of 22) rather than picked for
# convenience, so a replay at ARM_C is as crowded as the run that produced
# 1327 distinct tracks for 22 players. On the pre-fix code this replay minted
# 0.027 to 0.018 ids per detection against the real runs' 0.010 to 0.013, so it
# is the harder of the two and its verdicts are conservative.
ARM_A = 0.45
ARM_B = 0.55
ARM_C = 0.70


def build_replay(
    frames: int = 900,
    detect_quality: float = 0.32,
    seed: int = 11,
    noise: float = 0.5,
    drop_prob: float = 0.08,
    crowd_drop: float = 0.25,
    churn_prob: float = 0.004,
    crowd_churn: float = 0.06,
    swap_prob: float = 0.12,
    crowd_radius: float = 3.0,
    wobble: float = 0.7,
    tracker_buffer: int = 2,
) -> Replay:
    """Degrade a clean simulation the way the real detection stack does.

    Visibility is a two-state chain per player, not an independent coin flip
    per frame, because that is how detection actually fails: a player who is
    behind someone, edge-on, or at the far touchline stays missing for a run of
    frames and then comes back. Independent dropout would produce almost no
    gaps longer than one frame and would make re-ID look far easier than it is.

    ``detect_quality`` is the per-frame chance of recovering a missing player
    standing on the ball; distance from the ball discounts it, and ``drop_prob``
    (raised to ``crowd_drop`` when someone is close enough to occlude) is the
    chance of losing a visible one. The stationary visible fraction is
    recover / (recover + drop), so 0.24 and 0.32 against a 0.08 drop give the
    0.71 and 0.80 of 22 players per frame that the real arms A and C reported.

    ``wobble`` is a per-frame offset applied to *every* observation in the
    frame: the pipeline recomputes the homography per frame on a panning
    camera, so its error moves the whole pitch at once rather than jittering
    players independently. Per-identity prediction has no defence against it.

    ``tracker_buffer`` is how many sampled frames the base tracker will coast
    an unmatched track before dropping it. Ultralytics keeps 30 source frames,
    which at stride 3 is 10 sampled ones, but association failures mean it
    rarely reaches that in a crowd.
    """
    rng = np.random.default_rng(seed)
    truth, balls = _true_positions(frames, rng)

    raw_of = [0] * PLAYERS              # base tracker's current id per player
    next_raw = 1
    visible = np.zeros(PLAYERS, dtype=bool)
    last_seen = np.full(PLAYERS, -10_000, dtype=int)
    shift = np.zeros(2)
    out: List[List[Tuple[int, Tuple[float, float], int]]] = []

    for f, pos in enumerate(truth):
        ball_dist = np.linalg.norm(pos - balls[f], axis=1)
        recover = detect_quality * np.exp(-ball_dist / BALL_FALLOFF)
        # Far players also localise worse: a smaller box puts its foot point
        # further from the truth once it goes through the homography.
        spread = noise * (1.0 + ball_dist / 25.0)
        shift = 0.8 * shift + rng.normal(0.0, wobble, 2)
        # Neighbours within crowd_radius are the ones who occlude each other and
        # confuse the base tracker's association step.
        deltas = pos[:, None, :] - pos[None, :, :]
        dist = np.linalg.norm(deltas, axis=2)
        np.fill_diagonal(dist, np.inf)
        crowded = dist.min(axis=1) < crowd_radius

        for i in range(PLAYERS):
            if visible[i]:
                lose = crowd_drop if crowded[i] else drop_prob
                visible[i] = rng.random() >= lose
            else:
                visible[i] = rng.random() < recover[i]
        seen_now = [i for i in range(PLAYERS) if visible[i]]

        for i in seen_now:
            gap = f - last_seen[i]
            if raw_of[i] == 0 or gap > tracker_buffer:
                fresh = True                # coasted past its buffer, id retired
            else:
                # Inside its own buffer the base tracker usually holds on — but
                # in a crowd its association step has nothing to work with. IOU
                # overlaps the wrong box and the appearance embedding of one
                # player in a kit is the embedding of every player in that kit,
                # so it drops the track and mints a new id mid-run.
                fresh = rng.random() < (crowd_churn if crowded[i] else churn_prob)
            if fresh:
                next_raw += 1
                raw_of[i] = next_raw
            last_seen[i] = f

        # Crowded pairs occasionally have their raw ids exchanged: BoT-SORT
        # associating the wrong box, which is the failure re-ID must survive.
        for a in seen_now:
            for b in seen_now:
                if b > a and dist[a, b] < 2.0 and rng.random() < swap_prob:
                    raw_of[a], raw_of[b] = raw_of[b], raw_of[a]

        frame = [
            (
                raw_of[i],
                (
                    float(pos[i, 0] + shift[0] + rng.normal(0.0, spread[i])),
                    float(pos[i, 1] + shift[1] + rng.normal(0.0, spread[i])),
                ),
                i,
            )
            for i in seen_now
        ]
        rng.shuffle(frame)                  # detection order is arbitrary
        out.append(frame)

    return Replay(frames=out)



def run_replay(replay: Replay, mgr: IdentityManager) -> Dict[str, float]:
    """Push a replay through a manager and score identity quality.

    Three numbers matter, and quoting any one alone is a way to be wrong:

    ``ids_per_player``  how many canonical ids were minted per real player.
                        1.0 is perfect permanence; the fragmentation this
                        workstream exists to fix shows up here.
    ``purity``          of all detections, the share whose canonical id spends
                        most of its life on that same player. Falls when a
                        loose gate lets one identity swallow two players — the
                        cheap way to make ids_per_player look good.
    ``coverage``        of all detections, the share carried by their player's
                        single most-used id. Falls when a player is split
                        across many ids even if each id is pure.
    """
    pairs: Dict[Tuple[int, int], int] = {}      # (cid, player) -> detections
    for index in range(len(replay.frames)):
        resolved = mgr.update(index, replay.observations(index))
        for raw, _, player in replay.frames[index]:
            key = (resolved[raw], player)
            pairs[key] = pairs.get(key, 0) + 1

    total = sum(pairs.values())
    by_cid: Dict[int, Dict[int, int]] = {}
    by_player: Dict[int, Dict[int, int]] = {}
    for (cid, player), n in pairs.items():
        by_cid.setdefault(cid, {})[player] = n
        by_player.setdefault(player, {})[cid] = n

    purity = sum(max(v.values()) for v in by_cid.values()) / total
    coverage = sum(max(v.values()) for v in by_player.values()) / total

    out = mgr.summary()
    out["ids_per_player"] = mgr.total_identities / PLAYERS
    out["purity"] = purity
    out["coverage"] = coverage
    out["quality"] = (
        2 * purity * coverage / (purity + coverage) if purity + coverage else 0.0
    )
    out["mean_ids_per_player"] = float(
        np.mean([len(v) for v in by_player.values()])
    )
    return out


# --------------------------------------------------------------------------- #
# Replay tests
# --------------------------------------------------------------------------- #

def test_replay_is_actually_messy():
    """Guard the guard: a clean replay would make the acceptance test a lie.

    Arm C settings should land near the real run's 17.6 players per frame, and
    the base tracker underneath should be handing over a four-figure stream of
    raw ids for 22 people — which is the problem re-ID exists to solve.
    """
    replay = build_replay(frames=900, detect_quality=ARM_C, seed=11)
    per_frame = replay.detections / 900
    assert 16.5 <= per_frame <= 18.5
    assert replay.raw_id_count > 800
    # Gaps must be bursty, not one frame here and there. The base tracker
    # bridges absences up to its own buffer by itself; anything longer is
    # re-ID's problem, and a replay where those are rare would not test it.
    # A quarter of absences outlasting the buffer is the floor worth having.
    gaps = _gap_lengths(replay)
    assert np.median(gaps) >= 2
    assert float((gaps > 2).mean()) >= 0.25


def _gap_lengths(replay: Replay) -> np.ndarray:
    """How many frames each player spends missing, per absence."""
    last = {}
    out = []
    for index, frame in enumerate(replay.frames):
        for _, _, player in frame:
            if player in last and index - last[player] > 1:
                out.append(index - last[player] - 1)
            last[player] = index
    return np.array(out)


def test_smooth_players_keep_one_id_each():
    """The core invariant, with the messiness dialled off.

    22 players, nobody ever lost once found, no id churn, no swaps, only
    homography-scale jitter. There is nothing here to explain a second id for
    anybody: each player spawns once on the frame they are first detected and
    keeps that id for the rest of the replay.
    """
    replay = build_replay(
        frames=400, detect_quality=1.0, seed=5, drop_prob=0.0, crowd_drop=0.0,
        churn_prob=0.0, crowd_churn=0.0, swap_prob=0.0,
    )
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    result = run_replay(replay, mgr)
    assert result["total_identities"] == PLAYERS
    assert result["purity"] == pytest.approx(1.0)
    assert result["coverage"] == pytest.approx(1.0)


@pytest.mark.parametrize("arm", [ARM_A, ARM_B, ARM_C])
def test_replay_collapses_toward_the_real_squad(arm):
    """The acceptance criterion, in the only form CI can run.

    The base tracker hands over roughly 1300 raw ids for 22 players — about 60
    fragments each. Re-ID has to bring that down by more than an order of
    magnitude, to at most five ids per player, which is where per-player stats
    start being worth reporting.

    The quality floor is there to stop the id count being "fixed" the cheap
    way. Opening the gate wide enough and every player collapses into one
    identity, which scores beautifully on count and is worthless. Quality is
    the harmonic mean of how single-player each identity is and how much of a
    player's life their main identity covers, so it falls if ids fragment *or*
    if they merge. The pre-fix code scored 0.23 to 0.32 on it.
    """
    replay = build_replay(frames=900, detect_quality=arm, seed=11)
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    result = run_replay(replay, mgr)
    assert result["ids_per_player"] <= 5.0
    assert result["total_identities"] < replay.raw_id_count / 10
    assert result["quality"] >= 0.45


def test_better_detection_does_not_cost_more_identities():
    """The pathology this workstream exists to kill.

    On real footage, raising detection quality raised the track count: 936 ->
    1093 -> 1327 for 15.62 -> 16.61 -> 17.60 players per frame. More evidence
    about the same 22 people must not buy more identities for them, so the
    best-detection arm may not finish worse than the worst-detection one.

    Note what this test does and does not prove. Nothing inside this module
    reproduces that rise: detection rate, crowd density and gap length were all
    varied here and the pre-fix code's ids-per-detection was flat or falling
    against every one of them. The extra 391 tracks arm C bought cost about 30
    detections each, against 80 for the average arm-C track, which is the
    signature of short-lived marginal detections — people at the frame edge,
    touchline staff, half-occluded boxes — rather than of better coverage of
    the existing 22. Filtering those belongs upstream, in the pipeline.
    """
    counts = []
    for arm in (ARM_A, ARM_C):
        replay = build_replay(frames=900, detect_quality=arm, seed=11)
        mgr = IdentityManager(gate=6.0, max_lost_frames=45)
        counts.append(run_replay(replay, mgr)["total_identities"])
    assert counts[1] <= counts[0]


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_the_result_is_not_a_property_of_one_lucky_seed(seed):
    """Same conclusion on four other matches, so the thresholds mean something."""
    replay = build_replay(frames=600, detect_quality=ARM_C, seed=seed)
    mgr = IdentityManager(gate=6.0, max_lost_frames=45)
    result = run_replay(replay, mgr)
    assert result["ids_per_player"] <= 5.0
    assert result["quality"] >= 0.45


def test_detection_order_does_not_change_the_answer():
    """A frame is solved as a whole, so shuffling the boxes changes nothing.

    Order dependence is what made the old nearest-free-identity pass mis-assign
    under crowding, and it is invisible in aggregate numbers — the run looks
    fine, it is just resolving a different, arbitrary way each time.
    """
    replay = build_replay(frames=300, detect_quality=ARM_C, seed=9)
    forward = run_replay(replay, IdentityManager(gate=6.0, max_lost_frames=45))

    rng = np.random.default_rng(4)
    shuffled = Replay(frames=[list(frame) for frame in replay.frames])
    for frame in shuffled.frames:
        rng.shuffle(frame)
    reversed_order = run_replay(
        shuffled, IdentityManager(gate=6.0, max_lost_frames=45)
    )
    assert forward["total_identities"] == reversed_order["total_identities"]
    assert forward["quality"] == pytest.approx(reversed_order["quality"])
