#!/usr/bin/env python3
"""
Kickoff Pulse — the metric registry.

Every metric is **declared once** here: what it means, what it reads, how it is
aggregated, how far it can be trusted, and which version of the definition
produced a given number.

Before this, "stats" meant sixteen hard-coded strings in ``stats.py`` and
thirteen weights in ``insights.py``, with no definition or provenance attached to
any of them. Adding a full modern taxonomy to that shape would have become
unmaintainable within a month, and every number would have arrived with equal
apparent authority regardless of whether a human saw it or a model guessed it.

Two rules make the rest of the programme possible:

1. **A metric is a query plus an aggregation**, not a function. New metrics are
   registry entries, not edits across nine files.
2. **Definitions are versioned.** Changing what "progressive pass" means creates
   ``progressive_passes@2``; it never silently rewrites history.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Dict, Iterable, List, Optional

from .query import (EventQuery, MEASURED, PROJECTED, ZONE_ESTIMATE,
                    coordinate_provenance, progression_m, select)

# How a metric's value is produced from the events its query selected.
AGGREGATIONS = ("count", "sum", "mean", "ratio", "distinct")

# Where a metric's inputs come from. Confidence descends down this list, and it
# is what lets a report say which numbers a human saw and which a model inferred.
SOURCE_LOGGED = "logged"      # a person narrated or typed it
SOURCE_DERIVED = "derived"    # computed from logged events
SOURCE_VISION = "vision"      # from camera positions
SOURCE_BALL = "ball"          # needs reliable ball tracking
SOURCE_MODEL = "model"        # a versioned estimate (xG, xT, ...)

SOURCE_CONFIDENCE = {
    SOURCE_LOGGED: "high",
    SOURCE_DERIVED: "high",
    SOURCE_VISION: "indicative",
    SOURCE_BALL: "indicative",
    SOURCE_MODEL: "modelled",
}


@dataclass(frozen=True)
class Metric:
    """One metric definition. Data, not code — so it can be catalogued."""

    name: str
    display: str
    description: str
    entity: str                      # "team" | "player" | "both"
    category: str                    # passing | shooting | defending | ...
    source: str                      # SOURCE_*
    query: EventQuery
    aggregation: str = "count"
    value_field: Optional[str] = None       # for sum/mean
    denominator: Optional["Metric"] = None  # for ratio
    unit: str = ""
    version: int = 1
    supports_per90: bool = True
    supports_percentile: bool = True
    # Metrics whose meaning depends on coordinates should say so, so a report can
    # avoid presenting a zone-estimated distance as if it were measured.
    needs_coordinates: bool = False

    @property
    def key(self) -> str:
        """Stable identifier including the definition version."""
        return f"{self.name}@{self.version}"

    @property
    def confidence(self) -> str:
        return SOURCE_CONFIDENCE.get(self.source, "unknown")


@dataclass
class MetricResult:
    """A computed value, carrying enough context to be believed or doubted."""

    metric: Metric
    value: float
    events: List[dict] = field(default_factory=list)
    provenance: str = "unknown"
    note: str = ""

    @property
    def clip_anchors(self) -> List[dict]:
        """The events behind the number — what a clip can be cut from.

        A number in a table is a claim; twenty seconds of video is evidence.
        """
        return self.events


# --------------------------------------------------------------------------- #
# Computation
# --------------------------------------------------------------------------- #
def compute(metric: Metric, events: Iterable[dict],
            scope: Optional[EventQuery] = None) -> MetricResult:
    """Evaluate one metric over an event log.

    `scope` narrows the whole calculation (a team, a half, a game state) without
    the metric having to know about it — this is what makes "the same metric,
    but only while drawing" free rather than a second definition.
    """
    events = list(events or [])
    if scope is not None:
        events = select(events, scope)
    matched = select(events, metric.query)

    if metric.aggregation == "count":
        value = float(len(matched))
    elif metric.aggregation == "distinct":
        value = float(len({e.get(metric.value_field) for e in matched
                           if e.get(metric.value_field) is not None}))
    elif metric.aggregation in ("sum", "mean"):
        values = [_numeric(e, metric.value_field) for e in matched]
        values = [v for v in values if v is not None]
        if metric.aggregation == "sum":
            value = float(sum(values))
        else:
            value = float(sum(values) / len(values)) if values else 0.0
    elif metric.aggregation == "ratio":
        denom_events = (select(events, metric.denominator.query)
                        if metric.denominator else events)
        value = (100.0 * len(matched) / len(denom_events)) if denom_events else 0.0
    else:
        raise ValueError(f"Unknown aggregation {metric.aggregation!r}")

    return MetricResult(metric=metric, value=value, events=matched,
                        provenance=_provenance_of(metric, matched),
                        note=_note_for(metric, matched))


def _numeric(event: dict, field_name: Optional[str]):
    if field_name == "__progression__":
        return progression_m(event)
    if not field_name:
        return None
    try:
        return float(event.get(field_name))
    except (TypeError, ValueError):
        return None


def _provenance_of(metric: Metric, matched: List[dict]) -> str:
    """The weakest coordinate provenance among the events behind a number.

    Deliberately the weakest: a distance averaged over ten measured shots and one
    zone-estimated shot is not a measurement, and saying so is the whole point.
    """
    if not metric.needs_coordinates:
        return metric.source
    if not matched:
        return "unknown"
    ranks = {coordinate_provenance(e) for e in matched}
    for tier in (ZONE_ESTIMATE, PROJECTED, MEASURED):
        if tier in ranks:
            return tier
    return "unknown"


def _note_for(metric: Metric, matched: List[dict]) -> str:
    if metric.needs_coordinates and matched:
        prov = _provenance_of(metric, matched)
        if prov == ZONE_ESTIMATE:
            return ("Positions come from described zones, so this is accurate to "
                    "a zone and not to a metre.")
        if prov == PROJECTED:
            return ("Positions are in image space (uncalibrated or panning "
                    "camera), so distances are directional.")
    if metric.source == SOURCE_VISION:
        return "From camera detections; grades with the run's quality."
    return ""


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #
REGISTRY: Dict[str, Metric] = {}


def register(metric: Metric) -> Metric:
    if metric.name in REGISTRY and REGISTRY[metric.name].version == metric.version:
        raise ValueError(f"{metric.name}@{metric.version} is already registered")
    REGISTRY[metric.name] = metric
    return metric


def get(name: str) -> Metric:
    if name not in REGISTRY:
        raise KeyError(f"No metric named {name!r}")
    return REGISTRY[name]


def by_category(category: str) -> List[Metric]:
    return [m for m in REGISTRY.values() if m.category == category]


def catalogue() -> List[dict]:
    """Machine-readable definitions, for docs and for the API layer later."""
    out = []
    for m in sorted(REGISTRY.values(), key=lambda m: (m.category, m.name)):
        out.append({
            "name": m.name, "key": m.key, "display": m.display,
            "description": m.description, "entity": m.entity,
            "category": m.category, "source": m.source,
            "confidence": m.confidence, "aggregation": m.aggregation,
            "unit": m.unit, "version": m.version,
            "supports": ([("per90" if m.supports_per90 else None),
                          ("percentile" if m.supports_percentile else None)]),
            "needs_coordinates": m.needs_coordinates,
        })
    return out


def per90(result: MetricResult, minutes: float) -> Optional[float]:
    """Normalise to 90 minutes, refusing to do so on a meaningless sample.

    A per-90 built from four minutes is not a rate, it is an extrapolation, and
    presenting it beside a full season's would be misleading.
    """
    if not result.metric.supports_per90 or not minutes or minutes < 20:
        return None
    return result.value / minutes * 90.0
