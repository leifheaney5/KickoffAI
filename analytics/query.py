#!/usr/bin/env python3
"""
Kickoff Pulse — the event query engine.

Metrics are **compositions of filters over events**, never hand-written
functions. That is the difference between a platform and a pile of counters: it
is what lets

    successful progressive forward passes under high pressure
    into the final third, by central midfielders, in the second half
    while drawing

be expressed without a new column, a new function, or a new table.

It is also the substrate for a natural-language layer: a model compiles a
question into an :class:`EventQuery`; the engine computes the answer. A language
model must never calculate a statistic itself.

Pure Python over plain dicts — no database, no Streamlit — so it runs in CI and
over either the live working log or rows read back from the library.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Sequence

# --------------------------------------------------------------------------- #
# Pitch geometry
#
# Coordinates are the normalised 0..100 tactical system the vision pipeline
# already emits, with x running toward the opponent goal.
# --------------------------------------------------------------------------- #
THIRDS = {"defensive": (0.0, 33.3), "middle": (33.3, 66.7), "final": (66.7, 100.0)}
CHANNELS = {"left": (0.0, 33.3), "central": (33.3, 66.7), "right": (66.7, 100.0)}
BOX_X, BOX_Y = 83.0, (21.0, 79.0)


def third_of(x: Optional[float]) -> Optional[str]:
    """Which third a normalised x sits in."""
    if x is None:
        return None
    for name, (lo, hi) in THIRDS.items():
        if lo <= x <= hi:
            return name
    return "final" if x > 100 else "defensive"


def channel_of(y: Optional[float]) -> Optional[str]:
    if y is None:
        return None
    for name, (lo, hi) in CHANNELS.items():
        if lo <= y <= hi:
            return name
    return "right" if y > 100 else "left"


def in_box(x: Optional[float], y: Optional[float]) -> bool:
    """True inside the opponent penalty area."""
    if x is None or y is None:
        return False
    return x >= BOX_X and BOX_Y[0] <= y <= BOX_Y[1]


def distance_to_goal(x: Optional[float], y: Optional[float]) -> Optional[float]:
    """Metres to the centre of the opponent goal, on a 105x68 m pitch."""
    if x is None or y is None:
        return None
    dx = (100.0 - x) / 100.0 * 105.0
    dy = (y - 50.0) / 100.0 * 68.0
    return (dx * dx + dy * dy) ** 0.5


def minute_of(event: dict) -> Optional[float]:
    """Match minute from `match_time` ("MM:SS", optionally "+M:SS")."""
    mt = (event.get("match_time") or "").strip()
    m = re.match(r"(\d+):(\d+)", mt)
    if not m:
        return None
    minute = int(m.group(1)) + int(m.group(2)) / 60.0
    add = re.search(r"\+(\d+):(\d+)", mt)
    if add:
        minute += int(add.group(1)) + int(add.group(2)) / 60.0
    return minute


def half_of(event: dict) -> Optional[int]:
    minute = minute_of(event)
    return None if minute is None else (1 if minute <= 45 else 2)


# --------------------------------------------------------------------------- #
# Provenance
#
# Every coordinate declares where it came from. Logged events carry no
# coordinates at all — `location` is free text like "box" — so a phrase mapped
# to a zone centroid is honest at zone resolution and must never be presented as
# a measurement.
# --------------------------------------------------------------------------- #
MEASURED = "measured"            # calibrated, fixed camera: true pitch metres
PROJECTED = "projected"          # vision, uncalibrated or panning: image space
ZONE_ESTIMATE = "zone_estimate"  # a logged phrase mapped to a zone centroid
UNKNOWN = "unknown"

PROVENANCE_RANK = {MEASURED: 3, PROJECTED: 2, ZONE_ESTIMATE: 1, UNKNOWN: 0}


def coordinate_provenance(event: dict) -> str:
    """How much the coordinates on this event can be believed."""
    return event.get("coord_provenance") or (
        PROJECTED if event.get("source") == "vision" and event.get("x") is not None
        else ZONE_ESTIMATE if event.get("x") is not None
        else UNKNOWN)


# --------------------------------------------------------------------------- #
# The query
# --------------------------------------------------------------------------- #
def _as_set(value) -> Optional[set]:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        return {value.lower()}
    return {str(v).lower() for v in value}


@dataclass(frozen=True)
class EventQuery:
    """A composable filter over events. Every field is optional and ANDed.

    Deliberately declarative: a query is data, so it can be stored in a metric
    definition, serialised into the metric catalogue, versioned, and produced by
    a language model without that model touching arithmetic.
    """

    action: Any = None                 # "pass" | ("pass", "cross") | None
    result: Any = None
    team: Any = None                   # "Home" | "Away"
    player: Any = None
    source: Any = None                 # "audio" | "vision"
    # Events arrive "pending" and count until a reviewer denies them — the app
    # has always worked that way, so the default excludes denied rather than
    # requiring approved. Requiring approval would silently zero a live match.
    exclude_status: Any = ("denied",)
    status: Any = None                 # set to require a specific status
    body_part: Any = None
    play_pattern: Any = None

    origin_third: Any = None
    destination_third: Any = None
    channel: Any = None
    into_box: Optional[bool] = None
    under_pressure: Optional[bool] = None

    half: Optional[int] = None
    minute_from: Optional[float] = None
    minute_to: Optional[float] = None

    min_progression_m: Optional[float] = None   # metres gained toward goal
    forward_only: bool = False

    min_provenance: Optional[str] = None        # e.g. require MEASURED
    predicate: Optional[Callable[[dict], bool]] = None

    def matches(self, e: dict) -> bool:
        if not self._field_ok(e, "action", self.action):
            return False
        if not self._field_ok(e, "result", self.result):
            return False
        if not self._field_ok(e, "team", self.team):
            return False
        if not self._field_ok(e, "player", self.player):
            return False
        if not self._field_ok(e, "body_part", self.body_part):
            return False
        if not self._field_ok(e, "play_pattern", self.play_pattern):
            return False

        if self.source is not None:
            src = e.get("source") or "audio"
            if src.lower() not in _as_set(self.source):
                return False
        status = (e.get("status") or "pending").lower()
        if self.exclude_status and status in _as_set(self.exclude_status):
            return False
        if self.status is not None and status not in _as_set(self.status):
            return False

        if self.under_pressure is not None:
            if bool(e.get("under_pressure")) is not self.under_pressure:
                return False

        if self.origin_third is not None:
            if third_of(e.get("x")) not in _as_set(self.origin_third):
                return False
        if self.destination_third is not None:
            if third_of(e.get("end_x")) not in _as_set(self.destination_third):
                return False
        if self.channel is not None:
            if channel_of(e.get("y")) not in _as_set(self.channel):
                return False
        if self.into_box is not None:
            if in_box(e.get("end_x"), e.get("end_y")) is not self.into_box:
                return False

        if self.half is not None and half_of(e) != self.half:
            return False
        minute = minute_of(e)
        if self.minute_from is not None and (minute is None
                                             or minute < self.minute_from):
            return False
        if self.minute_to is not None and (minute is None
                                           or minute > self.minute_to):
            return False

        if self.forward_only or self.min_progression_m is not None:
            gained = progression_m(e)
            if gained is None:
                return False
            if self.forward_only and gained <= 0:
                return False
            if (self.min_progression_m is not None
                    and gained < self.min_progression_m):
                return False

        if self.min_provenance is not None:
            need = PROVENANCE_RANK.get(self.min_provenance, 0)
            if PROVENANCE_RANK.get(coordinate_provenance(e), 0) < need:
                return False

        return self.predicate(e) if self.predicate else True

    @staticmethod
    def _field_ok(e: dict, key: str, wanted) -> bool:
        if wanted is None:
            return True
        value = e.get(key)
        if value is None:
            return False
        return str(value).lower() in _as_set(wanted)


def progression_m(event: dict) -> Optional[float]:
    """Metres the ball moved toward the opponent goal. None if unknown."""
    before = distance_to_goal(event.get("x"), event.get("y"))
    after = distance_to_goal(event.get("end_x"), event.get("end_y"))
    if before is None or after is None:
        return None
    return before - after


def select(events: Iterable[dict], query: EventQuery) -> list:
    """Every event matching the query, in order."""
    return [e for e in (events or []) if query.matches(e)]
