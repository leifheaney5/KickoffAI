#!/usr/bin/env python3
"""Kickoff Pulse — vision output schema.

Typed dataclasses that serialise to exactly the target ``match_stats.json``
shape. Keeping the schema in one place means the heuristics engine and the
pipeline never hand-roll dictionaries that drift out of spec.

Coordinates in the output are in the normalised 0..100 tactical pitch system.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Sequence


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def format_timestamp(seconds: float) -> str:
    """Format seconds as ``MM:SS.s`` (one decimal), e.g. 1.2 -> ``00:01.2``."""
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    remainder = seconds - 60 * minutes
    return f"{minutes:02d}:{remainder:04.1f}"


def side_code(team: Optional[str]) -> str:
    """Map a team label onto the id prefix letter (Home->A, Away->B)."""
    if team == "Home":
        return "A"
    if team == "Away":
        return "B"
    return "X"  # unknown / referee


def player_token(team: Optional[str], jersey: Optional[int], track_id: int) -> str:
    """Stable per-player identifier, e.g. ``TeamA_No10``.

    Falls back to the canonical track id (``TeamA_trk7``) until a jersey number
    has been bound to the player.
    """
    code = side_code(team)
    if jersey is not None:
        return f"Team{code}_No{int(jersey):02d}"
    return f"Team{code}_trk{track_id}"


def _round_xy(x: Optional[float], y: Optional[float]) -> List[Optional[float]]:
    return [
        None if x is None else round(float(x), 1),
        None if y is None else round(float(y), 1),
    ]


# --------------------------------------------------------------------------- #
# Per-frame tracking records
# --------------------------------------------------------------------------- #
@dataclass
class BallState:
    x: Optional[float]
    y: Optional[float]
    status: str = "unknown"   # "loose" | "in_flight" | "possessed_by_TeamA_No10"

    def to_dict(self) -> dict:
        x, y = _round_xy(self.x, self.y)
        return {"x": x, "y": y, "status": self.status}


@dataclass
class PlayerState:
    id: str
    jersey_number: Optional[int]
    team: Optional[str]
    x: float
    y: float

    def to_dict(self) -> dict:
        x, y = _round_xy(self.x, self.y)
        return {
            "id": self.id,
            "jersey_number": self.jersey_number,
            "team": self.team,
            "x": x,
            "y": y,
        }


@dataclass
class FrameRecord:
    timestamp: str
    frame_index: int
    ball: BallState
    players: List[PlayerState] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "frame_index": self.frame_index,
            "ball": self.ball.to_dict(),
            "players": [p.to_dict() for p in self.players],
        }


# --------------------------------------------------------------------------- #
# Statistical events
# --------------------------------------------------------------------------- #
@dataclass
class PassEvent:
    event_id: str
    timestamp: str
    passer: str
    intended_receiver: Optional[str]
    pass_type: str            # "ground_pass" | "lofted_pass" | "through_ball"
    outcome: str              # "completed" | "intercepted" | "incomplete"
    start_coords: Sequence[float]
    end_coords: Sequence[float]

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "passer": self.passer,
            "intended_receiver": self.intended_receiver,
            "pass_type": self.pass_type,
            "outcome": self.outcome,
            "start_coords": _round_xy(self.start_coords[0], self.start_coords[1]),
            "end_coords": _round_xy(self.end_coords[0], self.end_coords[1]),
        }


@dataclass
class PossessionSummary:
    team_home_percentage: float = 0.0
    team_away_percentage: float = 0.0

    def to_dict(self) -> dict:
        return {
            "team_home_percentage": round(self.team_home_percentage, 1),
            "team_away_percentage": round(self.team_away_percentage, 1),
        }


# --------------------------------------------------------------------------- #
# Top-level document
# --------------------------------------------------------------------------- #
@dataclass
class MatchStats:
    frame_rate_sampled: str
    frames: List[FrameRecord] = field(default_factory=list)
    passes: List[PassEvent] = field(default_factory=list)
    possession: PossessionSummary = field(default_factory=PossessionSummary)
    # "pitch" once a homography maps coordinates to true pitch metres, else
    # "image" (raw camera space — perspective-distorted, depth compressed).
    coordinate_space: str = "image"

    def to_dict(self) -> dict:
        return {
            "tracking_data": {
                "frame_rate_sampled": self.frame_rate_sampled,
                "coordinate_space": self.coordinate_space,
                "spatial_tracking_frames": [f.to_dict() for f in self.frames],
            },
            "statistical_events": {
                "passing_stats": [p.to_dict() for p in self.passes],
                "possession_summary": self.possession.to_dict(),
            },
        }

    def save(self, path: str) -> None:
        """Atomically write the document to ``path`` (rename is atomic)."""
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
