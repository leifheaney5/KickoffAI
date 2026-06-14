#!/usr/bin/env python3
"""Kickoff Pulse — local stats logic engine.

A frame-driven state machine that turns per-frame spatial observations into the
two headline outputs: **possession** and **passing events**. It works entirely
from geometry (no learned model), so every decision is inspectable and tunable
through :class:`~vision.config.PipelineConfig`.

Distances are evaluated in pitch **metres** (so the 1.5 m possession radius is
literal); emitted coordinates use the normalised 0..100 system.

Possession
----------
The nearest player to the ball within ``possession_radius_m`` is the candidate.
Once the same candidate holds for ``possession_frames`` consecutive sampled
frames, possession is *confirmed* for that player's team and every confirmed
frame is tallied toward the possession share.

Passing
-------
A small state machine tracks the ball between ``controlled`` and ``in_flight``:

* control -> loose          : the holder released the ball; remember the origin.
* in_flight -> new holder   : same team  -> completed pass; opponent -> interception.
* in_flight -> out of play  : ball left the pitch -> incomplete pass.
* in_flight -> timeout      : nobody controlled it in time -> incomplete pass.

Completed passes are typed (ground / lofted / through) from trajectory, speed,
mid-flight detection gaps and the space around the receiver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .config import PipelineConfig
from .homography import PitchHomography
from .schema import PassEvent, PossessionSummary, format_timestamp


@dataclass
class PlayerObs:
    """One player's resolved state for a single frame."""

    token: str
    team: Optional[str]
    xy_m: Tuple[float, float]       # pitch metres
    xy_norm: Tuple[float, float]    # normalised 0..100


@dataclass
class BallObs:
    """The ball's resolved state for a single frame (present == detected)."""

    xy_m: Tuple[float, float]
    xy_norm: Tuple[float, float]


class StatsEngine:
    """Consumes frames in order and accumulates possession + pass events."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.events: List[PassEvent] = []
        self.possession_frames: Dict[str, int] = {"Home": 0, "Away": 0}

        # Possession streak state.
        self._cand_token: Optional[str] = None
        self._streak = 0
        self._holder: Optional[PlayerObs] = None     # confirmed this frame

        # Pass state machine state.
        self._state = "idle"                         # idle | controlled | flight
        self._last_hold: Optional[PlayerObs] = None  # last confirmed holder
        self._from_token: Optional[str] = None
        self._from_team: Optional[str] = None
        self._start_norm: Optional[Tuple[float, float]] = None
        self._start_m: Optional[Tuple[float, float]] = None
        self._flight_t0 = 0.0
        self._flight_missing = 0
        self._last_ball_norm: Optional[Tuple[float, float]] = None
        self._last_ball_m: Optional[Tuple[float, float]] = None
        self._pass_counter = 0

    # ------------------------------------------------------------------ #
    def update(
        self,
        frame_index: int,
        t_sec: float,
        ball: Optional[BallObs],
        players: Sequence[PlayerObs],
    ) -> str:
        """Advance the engine by one sampled frame; return the ball status."""
        if ball is not None:
            self._last_ball_norm = ball.xy_norm
            self._last_ball_m = ball.xy_m

        holder = self._update_possession(ball, players)
        self._update_passing(frame_index, t_sec, ball, holder, players)

        # Build the ball status string for the frame record.
        if holder is not None:
            return f"possessed_by_{holder.token}"
        if self._state == "flight":
            return "in_flight"
        return "loose"

    # ------------------------------------------------------------------ #
    def _update_possession(
        self, ball: Optional[BallObs], players: Sequence[PlayerObs]
    ) -> Optional[PlayerObs]:
        """Update the streak counter and return the confirmed holder, if any."""
        nearest = self._nearest_player(ball, players)
        if nearest is None:
            self._cand_token = None
            self._streak = 0
            self._holder = None
            return None

        if nearest.token == self._cand_token:
            self._streak += 1
        else:
            self._cand_token = nearest.token
            self._streak = 1

        if self._streak >= self.config.possession_frames:
            self._holder = nearest
            if nearest.team in self.possession_frames:
                self.possession_frames[nearest.team] += 1
            return nearest

        self._holder = None
        return None

    def _nearest_player(
        self, ball: Optional[BallObs], players: Sequence[PlayerObs]
    ) -> Optional[PlayerObs]:
        if ball is None or not players:
            return None
        bx, by = ball.xy_m
        best: Optional[PlayerObs] = None
        best_dist = self.config.possession_radius_m
        for p in players:
            dist = float(np.hypot(p.xy_m[0] - bx, p.xy_m[1] - by))
            if dist <= best_dist:
                best_dist = dist
                best = p
        return best

    # ------------------------------------------------------------------ #
    def _update_passing(
        self,
        frame_index: int,
        t_sec: float,
        ball: Optional[BallObs],
        holder: Optional[PlayerObs],
        players: Sequence[PlayerObs],
    ) -> None:
        if holder is not None:
            self._on_controlled(holder, players, t_sec)
            self._last_hold = holder
            return

        # No confirmed holder this frame -> the ball is loose or in flight.
        if self._state == "controlled" and self._last_hold is not None:
            self._enter_flight(t_sec)
        elif self._state == "flight":
            self._continue_flight(t_sec, ball)

    def _on_controlled(
        self, holder: PlayerObs, players: Sequence[PlayerObs], t_sec: float
    ) -> None:
        """A player has confirmed control this frame."""
        if self._state == "flight" and self._from_token is not None:
            if holder.token != self._from_token:
                self._emit_reception(holder, players, t_sec)
            # Same player re-controlling is a touch/dribble: no event.
        self._state = "controlled"
        self._from_token = None

    def _enter_flight(self, t_sec: float) -> None:
        """The previous holder just released the ball."""
        origin = self._last_hold
        self._state = "flight"
        self._from_token = origin.token
        self._from_team = origin.team
        self._start_norm = origin.xy_norm
        self._start_m = origin.xy_m
        self._flight_t0 = t_sec
        self._flight_missing = 0

    def _continue_flight(self, t_sec: float, ball: Optional[BallObs]) -> None:
        """Ball is mid-flight with nobody in control yet."""
        if ball is None:
            self._flight_missing += 1
        elif not PitchHomography.is_inside(ball.xy_norm, margin=1.0):
            # Ball left the field of play -> incomplete pass.
            self._emit_incomplete(t_sec, end_norm=ball.xy_norm, end_m=ball.xy_m)
            return

        if (t_sec - self._flight_t0) > self.config.max_flight_seconds:
            # Nobody controlled it in time -> treat as an incomplete pass.
            self._emit_incomplete(
                t_sec,
                end_norm=self._last_ball_norm or self._start_norm,
                end_m=self._last_ball_m or self._start_m,
            )

    # ------------------------------------------------------------------ #
    def _emit_reception(
        self, receiver: PlayerObs, players: Sequence[PlayerObs], t_sec: float
    ) -> None:
        """Log a completed pass or an interception at the moment of control."""
        same_team = (
            receiver.team is not None
            and self._from_team is not None
            and receiver.team == self._from_team
        )
        start_m = self._start_m or receiver.xy_m
        end_m = receiver.xy_m
        dist_m = float(np.hypot(end_m[0] - start_m[0], end_m[1] - start_m[1]))
        if dist_m < self.config.min_pass_distance_m:
            # Too short to be a genuine pass (a tackle/scramble); skip.
            self._reset_flight()
            return

        elapsed = max(1e-3, t_sec - self._flight_t0)
        speed = dist_m / elapsed

        if same_team:
            pass_type = self._classify_pass(
                start_m, end_m, speed, receiver, players
            )
            outcome = "completed"
            intended = receiver.token
        else:
            pass_type = self._classify_pass(
                start_m, end_m, speed, receiver, players
            )
            outcome = "intercepted"
            intended = None  # we cannot know the intended team-mate

        self._append_event(
            t_sec,
            passer=self._from_token,
            receiver=intended,
            pass_type=pass_type,
            outcome=outcome,
            start_norm=self._start_norm,
            end_norm=receiver.xy_norm,
        )
        self._reset_flight()

    def _emit_incomplete(
        self,
        t_sec: float,
        end_norm: Optional[Tuple[float, float]],
        end_m: Optional[Tuple[float, float]],
    ) -> None:
        start_m = self._start_m
        speed = 0.0
        pass_type = "ground_pass"
        if start_m is not None and end_m is not None:
            dist_m = float(np.hypot(end_m[0] - start_m[0], end_m[1] - start_m[1]))
            elapsed = max(1e-3, t_sec - self._flight_t0)
            speed = dist_m / elapsed
            if self._flight_missing >= self.config.lofted_missing_frames or (
                speed >= self.config.lofted_speed_mps
            ):
                pass_type = "lofted_pass"
        self._append_event(
            t_sec,
            passer=self._from_token,
            receiver=None,
            pass_type=pass_type,
            outcome="incomplete",
            start_norm=self._start_norm,
            end_norm=end_norm or self._start_norm,
        )
        self._reset_flight()

    def _reset_flight(self) -> None:
        self._state = "idle"
        self._from_token = None
        self._from_team = None
        self._start_norm = None
        self._start_m = None
        self._flight_missing = 0

    # ------------------------------------------------------------------ #
    def _classify_pass(
        self,
        start_m: Tuple[float, float],
        end_m: Tuple[float, float],
        speed: float,
        receiver: PlayerObs,
        players: Sequence[PlayerObs],
    ) -> str:
        """Ground vs lofted vs through, from trajectory / speed / space."""
        dist_m = float(np.hypot(end_m[0] - start_m[0], end_m[1] - start_m[1]))
        lofted = (
            self._flight_missing >= self.config.lofted_missing_frames
            or speed >= self.config.lofted_speed_mps
        )

        # A through ball splits the defence: a forward pass of real length that
        # arrives with clear space around the receiver.
        forward = self._is_forward(start_m, end_m, self._from_team)
        if (
            forward
            and dist_m >= self.config.through_ball_min_distance_m
            and self._space_around(receiver, players)
            >= self.config.through_ball_space_m
        ):
            return "through_ball"
        return "lofted_pass" if lofted else "ground_pass"

    def _is_forward(
        self,
        start_m: Tuple[float, float],
        end_m: Tuple[float, float],
        team: Optional[str],
    ) -> bool:
        """True if the pass advances toward the team's attacking direction."""
        dx = end_m[0] - start_m[0]
        attacks_positive = self.config.home_attacks_positive_x
        if team == "Away":
            attacks_positive = not attacks_positive
        return dx > 0 if attacks_positive else dx < 0

    @staticmethod
    def _space_around(receiver: PlayerObs, players: Sequence[PlayerObs]) -> float:
        """Distance (m) from the receiver to the nearest opponent."""
        if receiver.team is None:
            return float("inf")
        rx, ry = receiver.xy_m
        nearest = float("inf")
        for p in players:
            if p.team is None or p.team == receiver.team:
                continue
            nearest = min(nearest, float(np.hypot(p.xy_m[0] - rx, p.xy_m[1] - ry)))
        return nearest

    # ------------------------------------------------------------------ #
    def _append_event(
        self,
        t_sec: float,
        passer: Optional[str],
        receiver: Optional[str],
        pass_type: str,
        outcome: str,
        start_norm: Optional[Tuple[float, float]],
        end_norm: Optional[Tuple[float, float]],
    ) -> None:
        self._pass_counter += 1
        self.events.append(
            PassEvent(
                event_id=f"pass_{self._pass_counter:03d}",
                timestamp=format_timestamp(t_sec),
                passer=passer or "unknown",
                intended_receiver=receiver,
                pass_type=pass_type,
                outcome=outcome,
                start_coords=start_norm or (0.0, 0.0),
                end_coords=end_norm or (0.0, 0.0),
            )
        )

    # ------------------------------------------------------------------ #
    def possession_summary(self) -> PossessionSummary:
        total = self.possession_frames["Home"] + self.possession_frames["Away"]
        if total == 0:
            return PossessionSummary(0.0, 0.0)
        home = 100.0 * self.possession_frames["Home"] / total
        return PossessionSummary(home, 100.0 - home)
