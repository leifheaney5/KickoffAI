#!/usr/bin/env python3
"""
Kickoff Pulse — the core metric definitions.

The sixteen stats the app has always computed, migrated from hard-coded counting
in ``stats.py`` onto the registry. This migration is deliberately the *first*
thing built on the registry: if the foundation cannot reproduce what already
works, exactly, it is not a foundation.

`tests/test_registry.py` asserts that against real match data.

Everything beyond these sixteen is added the same way — a declaration, not a
function — which is the whole point.
"""

from __future__ import annotations

from .query import EventQuery
from .registry import (Metric, SOURCE_DERIVED, SOURCE_LOGGED, register)

# Goals are logged either as a `goal` action or as a shot whose result is
# "scored"; both spellings come out of the parser and both have to count.
_GOAL = EventQuery(predicate=lambda e: (
    (e.get("action") or "").lower() == "goal"
    or (e.get("result") or "").lower() == "scored"))

_ON_TARGET = EventQuery(predicate=lambda e: (
    ((e.get("action") or "").lower() == "shot"
     and (e.get("result") or "").lower() in {"on target", "scored", "saved"})
    or (e.get("action") or "").lower() == "goal"
    or (e.get("result") or "").lower() == "scored"))

# A goal is also a shot, so "Shots" counts both spellings.
_SHOT = EventQuery(predicate=lambda e: (
    (e.get("action") or "").lower() in {"shot", "goal"}
    or (e.get("result") or "").lower() == "scored"))


def _card(colour: str) -> EventQuery:
    def is_card(e: dict) -> bool:
        action = (e.get("action") or "").lower()
        result = (e.get("result") or "").lower()
        return (action == "card" and colour in result) or action == f"{colour}_card"
    return EventQuery(predicate=is_card)


def _simple(name: str, display: str, action: str, category: str,
            description: str) -> Metric:
    return Metric(name=name, display=display, description=description,
                  entity="both", category=category, source=SOURCE_LOGGED,
                  query=EventQuery(action=action), aggregation="count")


CORE = [
    Metric(name="goals", display="Goals", entity="both", category="shooting",
           source=SOURCE_LOGGED, query=_GOAL, aggregation="count",
           description="Goals scored, however the event was phrased."),
    Metric(name="shots", display="Shots", entity="both", category="shooting",
           source=SOURCE_LOGGED, query=_SHOT, aggregation="count",
           description="Attempts at goal, including those that scored."),
    Metric(name="shots_on_target", display="On Target", entity="both",
           category="shooting", source=SOURCE_LOGGED, query=_ON_TARGET,
           aggregation="count",
           description="Attempts on target, including goals."),
    _simple("saves", "Saves", "save", "goalkeeping", "Goalkeeper saves."),
    _simple("tackles", "Tackles", "tackle", "defending", "Tackles made."),
    _simple("fouls", "Fouls", "foul", "discipline", "Fouls committed."),
    Metric(name="yellow_cards", display="Yellow Cards", entity="both",
           category="discipline", source=SOURCE_LOGGED, query=_card("yellow"),
           aggregation="count", description="Yellow cards received."),
    Metric(name="red_cards", display="Red Cards", entity="both",
           category="discipline", source=SOURCE_LOGGED, query=_card("red"),
           aggregation="count", description="Red cards received."),
    _simple("corners", "Corners", "corner", "set_piece", "Corners won."),
    _simple("offsides", "Offsides", "offside", "discipline", "Times caught offside."),
    _simple("passes", "Passes", "pass", "passing", "Passes attempted."),
    _simple("crosses", "Crosses", "cross", "passing", "Crosses attempted."),
    _simple("dribbles", "Dribbles", "dribble", "carrying", "Dribbles attempted."),
    _simple("interceptions", "Interceptions", "interception", "defending",
            "Interceptions made."),
    _simple("clearances", "Clearances", "clearance", "defending",
            "Clearances made."),
    _simple("substitutions", "Subs", "substitution", "squad",
            "Substitutions made."),
]

# Derived rates, expressed as ratios of two registry metrics rather than as
# bespoke arithmetic — so they inherit filtering and scoping for free.
_by_name = {m.name: m for m in CORE}

CORE += [
    Metric(name="shot_accuracy", display="Shot Accuracy", entity="both",
           category="shooting", source=SOURCE_DERIVED, query=_ON_TARGET,
           aggregation="ratio", denominator=_by_name["shots"], unit="%",
           supports_per90=False,
           description="Share of attempts that were on target."),
    Metric(name="shot_conversion", display="Shot Conversion", entity="both",
           category="shooting", source=SOURCE_DERIVED, query=_GOAL,
           aggregation="ratio", denominator=_by_name["shots"], unit="%",
           supports_per90=False,
           description="Share of attempts that were scored."),
]

for _m in CORE:
    register(_m)

# The display names the rest of the app already uses, so a stat block built from
# the registry is indistinguishable from the one it replaces.
LEGACY_ORDER = [
    "goals", "shots", "shots_on_target", "saves", "tackles", "fouls",
    "yellow_cards", "red_cards", "corners", "offsides", "passes", "crosses",
    "dribbles", "interceptions", "clearances", "substitutions",
]


def stat_block(events, team=None) -> dict:
    """The legacy 16-key stat block, computed entirely through the registry."""
    from .registry import compute, get

    scope = EventQuery(team=team) if team else EventQuery()
    return {get(name).display: int(compute(get(name), events, scope).value)
            for name in LEGACY_ORDER}
