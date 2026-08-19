#!/usr/bin/env python3
"""
Kickoff Pulse — the canonical football event taxonomy.

One place that says what an event *is*: which actions exist, which qualifiers may
attach to them, and how the many ways a person says a thing collapse onto one
canonical form.

Why this exists. The app grew a vocabulary of thirteen actions spread across a
parser prompt, a manual-entry form, a weights table and a stat aggregator, with
no single definition anywhere. Expanding toward a full modern taxonomy without
fixing that would have meant editing four places per action and hoping they
agreed.

Two rules:

1. **Absent means unknown, never zero.** Every qualifier is optional. A coach who
   narrates plainly still gets the stats they always got; the richer vocabulary
   expands what is *possible* to record, never what is *required*.
2. **Synonyms collapse here, not in the parser.** A model will say "headed",
   "header" and "with his head" on different days. All three mean one thing, and
   the mapping belongs in code that can be tested rather than in a prompt.
"""

from __future__ import annotations

from typing import Dict, Optional, Set

# --------------------------------------------------------------------------- #
# Actions, grouped as a coach would think of them
# --------------------------------------------------------------------------- #
SHOOTING = {"shot", "goal", "penalty"}
PASSING = {"pass", "cross", "through_ball", "long_ball", "cutback", "switch",
           "key_pass"}
CARRYING = {"dribble", "take_on", "carry", "miscontrol", "dispossessed"}
DEFENDING = {"tackle", "interception", "block", "clearance", "recovery",
             "pressure", "duel", "aerial_duel"}
GOALKEEPING = {"save", "claim", "punch", "smother", "sweeper_action",
               "keeper_pickup", "keeper_distribution"}
DISCIPLINE = {"foul", "card", "yellow_card", "red_card", "offside", "handball"}
RESTARTS = {"corner", "free_kick", "throw_in", "goal_kick", "kick_off",
            "drop_ball"}
SQUAD = {"substitution", "formation_change"}

ACTIONS: Set[str] = (SHOOTING | PASSING | CARRYING | DEFENDING | GOALKEEPING
                     | DISCIPLINE | RESTARTS | SQUAD)

# Actions that can carry a shot outcome, for xG and shot maps.
SHOT_ACTIONS = {"shot", "goal", "penalty"}

# Restarts that begin a set-piece phase.
SET_PIECES = {"corner", "free_kick", "throw_in", "goal_kick", "penalty"}

# What a defensive action is, for PPDA and pressing metrics.
DEFENSIVE_ACTIONS = {"tackle", "interception", "clearance", "block", "pressure",
                     "duel", "aerial_duel", "foul"}


# --------------------------------------------------------------------------- #
# Synonyms — how people actually speak
# --------------------------------------------------------------------------- #
ACTION_SYNONYMS: Dict[str, str] = {
    "shoots": "shot", "strike": "shot", "attempt": "shot", "effort": "shot",
    "scores": "goal", "scored": "goal", "finish": "goal",
    "assist": "key_pass", "assisted": "key_pass",
    "throughball": "through_ball", "through ball": "through_ball",
    "longball": "long_ball", "long ball": "long_ball",
    "pull back": "cutback", "pullback": "cutback",
    "takeon": "take_on", "take on": "take_on", "beat his man": "take_on",
    "nutmeg": "take_on",
    "lost the ball": "dispossessed", "turnover": "dispossessed",
    "bad touch": "miscontrol", "poor control": "miscontrol",
    "won the ball": "recovery", "recovers": "recovery", "recovered": "recovery",
    "header": "aerial_duel", "headed duel": "aerial_duel",
    "blocked": "block", "blocks": "block",
    "clears": "clearance", "cleared": "clearance",
    "intercepts": "interception", "intercepted": "interception",
    "tackles": "tackle", "tackled": "tackle",
    "booking": "yellow_card", "booked": "yellow_card",
    "sent off": "red_card", "dismissed": "red_card",
    "freekick": "free_kick", "free kick": "free_kick",
    "throwin": "throw_in", "throw in": "throw_in",
    "goalkick": "goal_kick", "goal kick": "goal_kick",
    "sub": "substitution", "substitute": "substitution",
    "catches": "claim", "caught": "claim", "punches": "punch",
    "sweeps": "sweeper_action", "rushes out": "sweeper_action",
}

# --------------------------------------------------------------------------- #
# Qualifiers — optional detail that attaches to an event
#
# Held as a flat mapping rather than as columns, so a new qualifier never needs a
# schema migration. This is the specification's §7 requirement, and the reason
# the taxonomy can grow without the event table growing with it.
# --------------------------------------------------------------------------- #
BODY_PARTS = {"left_foot", "right_foot", "head", "other"}
BODY_PART_SYNONYMS = {
    "left": "left_foot", "left foot": "left_foot", "lefty": "left_foot",
    "right": "right_foot", "right foot": "right_foot",
    "header": "head", "headed": "head", "with his head": "head",
    "head": "head", "chest": "other", "knee": "other", "shoulder": "other",
}

PLAY_PATTERNS = {"open_play", "corner", "free_kick", "throw_in", "goal_kick",
                 "penalty", "counter", "kick_off"}
PLAY_PATTERN_SYNONYMS = {
    "counter attack": "counter", "counterattack": "counter", "break": "counter",
    "fast break": "counter", "set piece": "free_kick", "from a corner": "corner",
}

SHOT_OUTCOMES = {"on_target", "off_target", "blocked", "woodwork", "scored",
                 "saved"}
SHOT_OUTCOME_SYNONYMS = {
    "on target": "on_target", "off target": "off_target", "wide": "off_target",
    "over": "off_target", "missed": "off_target", "miss": "off_target",
    "post": "woodwork", "bar": "woodwork", "crossbar": "woodwork",
    "hit the post": "woodwork", "saved": "saved", "blocked": "blocked",
    "scored": "scored", "goal": "scored",
}

# Every qualifier the taxonomy understands, with its allowed values. A qualifier
# absent from an event means unknown — never a zero, never a default.
QUALIFIERS: Dict[str, Optional[Set[str]]] = {
    "body_part": BODY_PARTS,
    "play_pattern": PLAY_PATTERNS,
    "shot_outcome": SHOT_OUTCOMES,
    "big_chance": None,          # boolean
    "under_pressure": None,      # boolean
    "first_time": None,          # boolean
    "assisted_by": None,         # free text: a player reference
    "distance_m": None,          # float, when known
}


def _canon(value, synonyms: Dict[str, str], allowed: Optional[Set[str]]):
    """Collapse a spoken value onto its canonical form, or None if unknown."""
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", " ")
    if not text:
        return None
    direct = text.replace(" ", "_")
    if allowed and direct in allowed:
        return direct
    if text in synonyms:
        return synonyms[text]
    for phrase, canon in synonyms.items():
        if phrase in text:
            return canon
    return direct if (allowed is None or direct in allowed) else None


def canonical_action(action) -> Optional[str]:
    """The canonical action name for whatever the parser produced."""
    return _canon(action, ACTION_SYNONYMS, ACTIONS)


def canonical_body_part(value) -> Optional[str]:
    return _canon(value, BODY_PART_SYNONYMS, BODY_PARTS)


def canonical_play_pattern(value) -> Optional[str]:
    return _canon(value, PLAY_PATTERN_SYNONYMS, PLAY_PATTERNS)


def canonical_shot_outcome(value) -> Optional[str]:
    return _canon(value, SHOT_OUTCOME_SYNONYMS, SHOT_OUTCOMES)


def is_shot(event: dict) -> bool:
    action = canonical_action(event.get("action"))
    return (action in SHOT_ACTIONS
            or canonical_shot_outcome(event.get("result")) == "scored")


def is_goal(event: dict) -> bool:
    return (canonical_action(event.get("action")) == "goal"
            or canonical_shot_outcome(event.get("result")) == "scored")


def is_defensive_action(event: dict) -> bool:
    return canonical_action(event.get("action")) in DEFENSIVE_ACTIONS


def normalise(event: dict) -> dict:
    """Return a copy of `event` with canonical action and qualifiers attached.

    Non-destructive: the original `action` and `result` are left as written so a
    reviewer can still see exactly what was said, and nothing is invented for a
    field the speaker did not supply.
    """
    out = dict(event)
    action = canonical_action(event.get("action"))
    if action:
        out["action_canonical"] = action

    body = canonical_body_part(event.get("body_part"))
    if body is None and action in SHOT_ACTIONS:
        # "headed goal" often arrives with the body part inside the phrasing.
        body = canonical_body_part(event.get("raw_text"))
    if body:
        out["body_part"] = body

    pattern = canonical_play_pattern(event.get("play_pattern"))
    if pattern is None and action in SET_PIECES:
        pattern = action if action in PLAY_PATTERNS else "free_kick"
    if pattern:
        out["play_pattern"] = pattern

    outcome = canonical_shot_outcome(event.get("shot_outcome")
                                     or event.get("result"))
    if outcome and is_shot(out):
        out["shot_outcome"] = outcome

    return out


def normalise_all(events) -> list:
    return [normalise(e) for e in (events or [])]


def vocabulary() -> dict:
    """The taxonomy as data, for the parser prompt and the docs."""
    return {
        "actions": sorted(ACTIONS),
        "qualifiers": {k: sorted(v) if v else "boolean/free"
                       for k, v in QUALIFIERS.items()},
    }
