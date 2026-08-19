#!/usr/bin/env python3
"""
Kickoff Pulse — metrics derived from events, possessions and models.

Everything here is computed rather than observed, so each declares
``SOURCE_DERIVED`` or ``SOURCE_MODEL`` and inherits the weaker confidence that
implies. A coach reading the report should be able to tell at a glance which
numbers a person saw and which the app worked out.

PPDA in particular exposes its numerator and denominator, because a pressing
number whose definition is hidden is a number nobody can argue with — and the
specification is right that the definitions must not be hidden.
"""

from __future__ import annotations

from typing import Optional

from football.taxonomy import DEFENSIVE_ACTIONS, canonical_action
from .query import EventQuery, in_box, select, third_of

# Minimum evidence before a derived number is worth stating at all. Both are
# arguments to nothing on purpose: they are honesty floors, not tuning knobs.
MIN_TILT_ACTIONS = 10
MIN_PPDA_PASSES = 10

# --------------------------------------------------------------------------- #
# Zone entries and territory
# --------------------------------------------------------------------------- #
def final_third_entries(events, team: str) -> int:
    """Possessions that reached the final third — territory that was earned."""
    from football import possessions as P

    return sum(1 for p in P.build(events)
               if p.team == team and p.reached_final_third)


def box_entries(events, team: str) -> int:
    from football import possessions as P

    return sum(1 for p in P.build(events) if p.team == team and p.reached_box)


def field_tilt(events, team: str, opponent: str) -> Optional[float]:
    """Share of final-third actions belonging to `team`.

    A better dominance signal than raw possession: holding the ball in your own
    half is not pressure. Returns None when neither side has any located action
    in the final third, which is common on a sparsely-narrated match.
    """
    def final_third_actions(side: str) -> int:
        return sum(1 for e in events
                   if e.get("team") == side
                   and (e.get("status") or "pending") != "denied"
                   and third_of(e.get("x")) == "final")

    ours, theirs = final_third_actions(team), final_third_actions(opponent)
    total = ours + theirs
    # A "tilt" computed from one or two located actions is noise wearing a
    # percentage sign. Most events carry no coordinates at all, so this stays
    # silent until there is enough located play to mean something.
    if total < MIN_TILT_ACTIONS:
        return None
    return round(100.0 * ours / total, 1)


# --------------------------------------------------------------------------- #
# Pressing
# --------------------------------------------------------------------------- #
def ppda(events, pressing_team: str, opponent: str,
         zone_from: float = 40.0) -> dict:
    """Opponent passes allowed per defensive action, in the pressing zone.

    Numerator and denominator are both returned, and the zone is an argument —
    a pressing metric whose definition is buried is one nobody can check.

    Lower means more aggressive pressing. `zone_from` is the normalised x beyond
    which the opponent's build-up counts, expressed in *their* attacking
    direction, which is our defensive half.
    """
    opponent_passes = [
        e for e in events
        if e.get("team") == opponent
        and (e.get("status") or "pending") != "denied"
        and canonical_action(e.get("action")) in {"pass", "cross", "long_ball",
                                                  "through_ball"}
        and (e.get("x") is None or e.get("x") >= zone_from)
    ]
    defensive_actions = [
        e for e in events
        if e.get("team") == pressing_team
        and (e.get("status") or "pending") != "denied"
        and canonical_action(e.get("action")) in DEFENSIVE_ACTIONS
        and (e.get("x") is None or e.get("x") <= (100.0 - zone_from))
    ]
    n, d = len(opponent_passes), len(defensive_actions)
    # No opponent passes means no data, not flawless pressing. Returning 0.0
    # here would read as the most aggressive press ever recorded.
    value = round(n / d, 2) if (d and n >= MIN_PPDA_PASSES) else None
    return {
        "ppda": value,
        "opponent_passes": n, "defensive_actions": d,
        "zone_from": zone_from,
        "unavailable": ("Not enough opponent passes were logged to measure "
                        "pressing." if value is None else ""),
        "definition": (f"Opponent passes made beyond x={zone_from:.0f} divided "
                       f"by {pressing_team}'s defensive actions in the same "
                       f"region. Lower means more aggressive pressing."),
    }


def high_turnovers(events, team: str, within_m: float = 40.0) -> list:
    """Possessions won close to the opponent goal — the pressing payoff."""
    from analytics.query import distance_to_goal
    from football import possessions as P

    out = []
    for p in P.build(events):
        if p.team != team or p.start_type != "turnover" or not p.events:
            continue
        first = p.events[0]
        dist = distance_to_goal(first.get("x"), first.get("y"))
        if dist is not None and dist <= within_m:
            out.append({"minute": p.start_minute, "distance_m": round(dist, 1),
                        "led_to_shot": p.ended_in_shot,
                        "led_to_goal": p.ended_in_goal})
    return out


# --------------------------------------------------------------------------- #
# Expected goals, summarised per team
# --------------------------------------------------------------------------- #
def team_expected_goals(events, team: str) -> dict:
    """xG for a team, with the model and the confidence behind it."""
    from models import xg as XG

    return XG.team_xg(events, team)


def match_summary(events, home: str = "Home", away: str = "Away") -> dict:
    """Everything derived, for one match, in one call.

    Assembled here so the report, the season view and any later API all read the
    same numbers rather than each recomputing them slightly differently.
    """
    from football.zones import enrich_all
    from football.taxonomy import normalise_all

    prepared = normalise_all(enrich_all(events))
    out = {}
    for side, other in ((home, away), (away, home)):
        out[side] = {
            "expected_goals": team_expected_goals(prepared, side),
            "final_third_entries": final_third_entries(prepared, side),
            "box_entries": box_entries(prepared, side),
            "field_tilt": field_tilt(prepared, side, other),
            "ppda": ppda(prepared, side, other),
            "high_turnovers": high_turnovers(prepared, side),
        }
    return out
