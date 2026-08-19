#!/usr/bin/env python3
"""
Kickoff Pulse — expected goals, done honestly.

xG is the headline modern metric and the easiest to fake. Real models train on
hundreds of thousands of shots; a youth side produces dozens a season. Fitting a
gradient-boosted model to that would be numerology with a confidence interval.

So this is a **published, transparent geometric model**. Every coefficient is
written below, printed in the report, and open to argument. It is labelled a
*model*, never a measurement, and it carries the resolution of the coordinates it
was given — a shot located only as "the box" produces a zone-accurate estimate
and says so.

Why not import a professional model: a Premier League xG surface assumes adult
finishing, adult goalkeeping and a full-size pitch. Applied to under-14s it would
be confidently wrong in a direction nobody could see. A simple model calibrated
to our own game is more useful and far more honest, and the coefficients can be
refit against our own shots as volume grows — which is precisely what owning the
data makes possible.

Versioned: changing a coefficient produces v2 and never silently rewrites what
last season's report said.
"""

from __future__ import annotations

import math
from typing import Optional

from analytics.query import ZONE_ESTIMATE, coordinate_provenance
from football.taxonomy import canonical_body_part, canonical_play_pattern, is_shot

VERSION = 1
MODEL_NAME = f"kickoff-geometric-xg@v{VERSION}"

# Pitch constants for the 0..100 normalised system, in metres.
PITCH_LENGTH_M, PITCH_WIDTH_M = 105.0, 68.0
GOAL_WIDTH_M = 7.32

# --------------------------------------------------------------------------- #
# Coefficients — the whole model, stated openly.
#
# A logistic surface over distance and visible goal angle, then multiplicative
# adjustments for the things that plainly change a chance. Values chosen to sit
# near published open-data baselines for distance/angle, then shifted for youth
# football: goalkeepers are weaker, so close-range chances convert more often,
# and long-range shots convert less than the adult game.
# --------------------------------------------------------------------------- #
# Solved against published open-data baselines for central shots — roughly
# 0.45 at six metres, 0.20 at eleven, 0.08 at the penalty-area edge — then the
# intercept lifted by 0.10 for youth football, where goalkeeping is weaker and
# close-range chances convert more often than in the adult game.
INTERCEPT = -0.068
DISTANCE_COEF = -0.1603     # per metre from goal
ANGLE_COEF = 0.8482         # per radian of visible goal

BODY_PART_FACTOR = {
    "head": 0.55,           # headers convert worse at equal geometry
    "left_foot": 1.0,
    "right_foot": 1.0,
    "other": 0.70,
}

PATTERN_FACTOR = {
    "penalty": None,        # handled separately — geometry does not apply
    "counter": 1.25,        # a stretched defence
    "corner": 0.80,         # congested, often headed
    "free_kick": 0.65,      # a set defence and a wall
    "throw_in": 0.90,
    "open_play": 1.0,
    "goal_kick": 1.0,
    "kick_off": 1.0,
}

BIG_CHANCE_FACTOR = 1.8
UNDER_PRESSURE_FACTOR = 0.75

# Youth penalties convert far below the adult ~0.78.
PENALTY_XG = 0.70

# A shot with no usable position at all still happened. Rather than drop it or
# invent a location, fall back to the average conversion of a located shot and
# mark the estimate as having no geometry behind it.
FALLBACK_XG = 0.09


def _distance_and_angle(x: float, y: float):
    """Metres to goal centre, and the radians of goal visible from the shot."""
    dx = (100.0 - x) / 100.0 * PITCH_LENGTH_M
    dy = (y - 50.0) / 100.0 * PITCH_WIDTH_M
    distance = math.hypot(dx, dy)

    # Angle subtended by the goal mouth from the shooting point.
    half = GOAL_WIDTH_M / 2.0
    if dx <= 0.01:
        angle = math.pi if abs(dy) < half else 0.0
    else:
        angle = abs(math.atan2(half - dy, dx) - math.atan2(-half - dy, dx))
    return distance, angle


def estimate(event: dict) -> Optional[dict]:
    """xG for one shot, with the reasoning attached. None if it is not a shot.

    Returns ``{xg, model, version, provenance, distance_m, angle_rad, factors}``
    so a report can show not just the number but why it is that number.
    """
    if not is_shot(event):
        return None

    pattern = canonical_play_pattern(event.get("play_pattern"))
    if (canonical_body_part(event.get("action")) is None
            and (event.get("action") or "").lower() == "penalty") or \
            pattern == "penalty":
        return {"xg": PENALTY_XG, "model": MODEL_NAME, "version": VERSION,
                "provenance": "rule", "distance_m": None, "angle_rad": None,
                "factors": {"penalty": PENALTY_XG},
                "note": "Penalties use a flat youth conversion rate, not geometry."}

    x, y = event.get("x"), event.get("y")
    if x is None or y is None:
        return {"xg": FALLBACK_XG, "model": MODEL_NAME, "version": VERSION,
                "provenance": "no_geometry", "distance_m": None,
                "angle_rad": None, "factors": {},
                "note": "No shot location was recorded, so this is the average "
                        "conversion of a located shot rather than an estimate "
                        "of this one."}

    distance, angle = _distance_and_angle(float(x), float(y))
    z = INTERCEPT + DISTANCE_COEF * distance + ANGLE_COEF * angle
    base = 1.0 / (1.0 + math.exp(-z))

    factors = {}
    body = canonical_body_part(event.get("body_part"))
    if body:
        factors["body_part"] = BODY_PART_FACTOR.get(body, 1.0)
    if pattern and PATTERN_FACTOR.get(pattern):
        factors["play_pattern"] = PATTERN_FACTOR[pattern]
    if event.get("big_chance"):
        factors["big_chance"] = BIG_CHANCE_FACTOR
    if event.get("under_pressure"):
        factors["under_pressure"] = UNDER_PRESSURE_FACTOR

    xg = base
    for f in factors.values():
        xg *= f
    xg = max(0.01, min(0.99, xg))

    prov = coordinate_provenance(event)
    note = ""
    if prov == ZONE_ESTIMATE:
        note = ("Shot position came from a described zone, so this is accurate "
                "to a zone rather than to a metre.")

    return {"xg": round(xg, 3), "model": MODEL_NAME, "version": VERSION,
            "provenance": prov, "distance_m": round(distance, 1),
            "angle_rad": round(angle, 3), "base": round(base, 3),
            "factors": factors, "note": note}


def annotate(events) -> list:
    """Attach `xg` to every shot in an event log, leaving others untouched."""
    out = []
    for e in events or []:
        est = estimate(e)
        out.append({**e, "xg": est["xg"], "xg_model": est["model"],
                    "xg_provenance": est["provenance"]} if est else e)
    return out


def team_xg(events, team: str) -> dict:
    """Total xG for a team, with the shots behind it and how solid it is."""
    shots, total, weakest = [], 0.0, "measured"
    order = {"measured": 3, "projected": 2, "zone_estimate": 1,
             "no_geometry": 0, "rule": 3}
    for e in events or []:
        if e.get("team") != team or (e.get("status") or "pending") == "denied":
            continue
        est = estimate(e)
        if not est:
            continue
        shots.append({**e, **{"xg": est["xg"]}})
        total += est["xg"]
        if order.get(est["provenance"], 0) < order.get(weakest, 3):
            weakest = est["provenance"]
    return {"xg": round(total, 2), "shots": len(shots), "detail": shots,
            "provenance": weakest if shots else "none", "model": MODEL_NAME}


def model_card() -> dict:
    """Everything needed to argue with this model."""
    return {
        "name": MODEL_NAME, "version": VERSION, "type": "logistic (geometric)",
        "features": ["distance to goal", "visible goal angle", "body part",
                     "play pattern", "big chance", "under pressure"],
        "coefficients": {"intercept": INTERCEPT, "distance": DISTANCE_COEF,
                         "angle": ANGLE_COEF},
        "factors": {"body_part": BODY_PART_FACTOR,
                    "play_pattern": {k: v for k, v in PATTERN_FACTOR.items() if v},
                    "big_chance": BIG_CHANCE_FACTOR,
                    "under_pressure": UNDER_PRESSURE_FACTOR},
        "special_cases": {"penalty": PENALTY_XG, "no_location": FALLBACK_XG},
        "fitted_on": "Not fitted. Coefficients are chosen from published "
                     "open-data baselines and adjusted for youth football; they "
                     "are intended to be refit against our own shots once "
                     "enough have been recorded.",
        "caveat": "A model, not a measurement. Treat it as a way of comparing "
                  "chances, not as the number of goals that should have been "
                  "scored.",
    }
