#!/usr/bin/env python3
"""
Kickoff Pulse — pitch zones and the coordinate bridge.

Spatial analytics need x/y on every event. Vision supplies them; the Ear does
not — a logged event carries a free-text `location` like "box" or "left wing",
and in the real match log it is absent 217 times in 223.

This module bridges that gap by mapping a described place to a zone, and a zone
to its centroid. The result is honest **at zone resolution and no finer**, which
is why everything it produces is tagged ``zone_estimate`` and never presented as
a measurement.

Two design rules:

1. **Refuse rather than guess.** A phrase the vocabulary does not recognise
   returns nothing. The real log contains "utah, iowa" — a transcription error —
   and inventing a pitch position for it would be worse than having none.
2. **Partial descriptions stay partial.** "Left wing" fixes the channel but not
   the third; the unstated half of the position is filled from the middle and the
   result is marked lower confidence, rather than pretending the phrase said more
   than it did.

Coordinates are the normalised 0..100 system the vision pipeline already emits,
oriented so **x=100 is the goal the acting team is attacking**. That matches
`analytics.query.distance_to_goal`, so no per-team flipping is needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Bands along the direction of play and across it.
THIRD_CENTRES = {"defensive": 16.7, "middle": 50.0, "final": 83.3}
CHANNEL_CENTRES = {"left": 16.7, "central": 50.0, "right": 83.3}

# Named areas that pin both axes at once.
AREAS = {
    "penalty_box":  (91.5, 50.0),
    "six_yard_box": (96.5, 50.0),
    "penalty_spot": (88.0, 50.0),
    "zone_14":      (78.0, 50.0),   # central, just outside the box
    "own_box":      (8.5, 50.0),
    "halfway":      (50.0, 50.0),
}


@dataclass(frozen=True)
class ZoneEstimate:
    """A place on the pitch inferred from a phrase, with its own caveat."""

    x: float
    y: float
    label: str
    confidence: str          # "area" (both axes stated) | "partial" (one axis)
    phrase: str = ""

    def as_coords(self) -> dict:
        """Fields to merge onto an event."""
        return {"x": round(self.x, 1), "y": round(self.y, 1),
                "zone_label": self.label, "coord_provenance": "zone_estimate",
                "zone_confidence": self.confidence}


# Phrase vocabulary. Ordered longest-first at match time so "own box" is not
# swallowed by "box", and "edge of the box" beats both.
_AREA_PHRASES = [
    (r"\b(six|6)[- ]?yard\b", "six_yard_box"),
    (r"\b(edge|top) of (the )?(box|area|18)\b", "zone_14"),
    (r"\bzone ?14\b", "zone_14"),
    (r"\bpenalty spot\b", "penalty_spot"),
    (r"\b(our|own) (box|area|penalty area)\b", "own_box"),
    # Bare "box" is the commonest phrasing in real logs, so it must match on
    # its own — "own box" is caught above, so ordering keeps them apart.
    (r"\b(penalty (box|area)|18[- ]?yard|box|penalty area)\b", "penalty_box"),
    (r"\b(halfway|half[- ]way|centre circle|center circle|kick[- ]?off spot)\b",
     "halfway"),
]

_THIRD_PHRASES = [
    (r"\b(final|attacking|last) third\b", "final"),
    (r"\b(defensive|defending|own|back) third\b", "defensive"),
    (r"\b(middle|central|centre|center|mid) third\b", "middle"),
    (r"\b(midfield|middle of the park)\b", "middle"),
    (r"\b(our|own) half\b", "defensive"),
    (r"\b(their|opposition|opponents?) half\b", "final"),
]

_CHANNEL_PHRASES = [
    (r"\bleft (wing|flank|channel|side|touchline)\b", "left"),
    (r"\bright (wing|flank|channel|side|touchline)\b", "right"),
    (r"\bleft half[- ]?space\b", "left"),
    (r"\bright half[- ]?space\b", "right"),
    (r"\b(centre|center|central|middle)\b", "central"),
    (r"\bleft\b", "left"),
    (r"\bright\b", "right"),
]


def _first_match(phrase: str, table) -> Optional[str]:
    for pattern, value in table:
        if re.search(pattern, phrase):
            return value
    return None


def resolve(location: Optional[str]) -> Optional[ZoneEstimate]:
    """Turn a described place into a zone estimate, or None if unrecognised.

    Returning None is a feature: an unmapped phrase leaves the event without
    coordinates, and a metric that needs them simply excludes it, which is
    correct. Fabricating a position would quietly corrupt every spatial metric
    built on top.
    """
    if not location:
        return None
    phrase = re.sub(r"[^a-z0-9 ]+", " ", str(location).lower()).strip()
    phrase = re.sub(r"\s+", " ", phrase)
    if not phrase:
        return None

    area = _first_match(phrase, _AREA_PHRASES)
    if area:
        x, y = AREAS[area]
        return ZoneEstimate(x, y, area, "area", phrase)

    third = _first_match(phrase, _THIRD_PHRASES)
    channel = _first_match(phrase, _CHANNEL_PHRASES)
    if third is None and channel is None:
        return None                      # unrecognised — say nothing

    # Whichever axis the phrase left unstated is filled from the middle, and the
    # estimate is marked partial so a caller can weigh it accordingly.
    x = THIRD_CENTRES[third] if third else THIRD_CENTRES["middle"]
    y = CHANNEL_CENTRES[channel] if channel else CHANNEL_CENTRES["central"]
    label = "_".join(p for p in (third, channel) if p)
    confidence = "area" if (third and channel) else "partial"
    return ZoneEstimate(x, y, label, confidence, phrase)


def enrich(event: dict) -> dict:
    """Return a copy of `event` with zone-estimated coordinates where possible.

    Never overwrites coordinates that already exist: vision-measured positions
    always outrank a described one, and silently replacing them would be the
    exact provenance failure this module exists to avoid.
    """
    if event.get("x") is not None:
        return event
    est = resolve(event.get("location"))
    if est is None:
        return event
    return {**event, **est.as_coords()}


def enrich_all(events) -> list:
    """Bridge a whole event log. Cheap, pure, and safe to run repeatedly."""
    return [enrich(e) for e in (events or [])]
