"""Tests for the metric registry and query engine.

The load-bearing test is `test_registry_reproduces_the_legacy_stat_block`: if the
foundation cannot reproduce exactly what the app already computed, it is not a
foundation. It caught a real design error — the query defaulted to requiring
`status="approved"`, but events arrive `pending` and count until denied, so every
live match would have shown zeros.
"""

import pytest

import analytics as A
import stats as S
from analytics import EventQuery, compute, get, select


def ev(action=None, team="Home", result=None, match_time="10:00",
       status="pending", **extra):
    e = {"action": action, "team": team, "result": result,
         "match_time": match_time, "status": status}
    e.update(extra)
    return e


# --------------------------------------------------------------------------- #
# The migration proof
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("team", ["Home", "Away"])
def test_registry_reproduces_the_legacy_stat_block(sample_events, team):
    assert A.stat_block(sample_events, team) == S.team_stats(sample_events, team)


def test_pending_events_count_until_denied():
    """The default that got this wrong first time round."""
    events = [ev("shot", status="pending"), ev("shot", status="approved"),
              ev("shot", status="denied")]

    assert compute(get("shots"), events).value == 2


# --------------------------------------------------------------------------- #
# Query composition — the point of the whole design
# --------------------------------------------------------------------------- #
def test_a_metric_can_be_scoped_without_new_code():
    events = [ev("shot", match_time="10:00"), ev("shot", match_time="60:00"),
              ev("shot", match_time="80:00")]

    assert compute(get("shots"), events).value == 3
    assert compute(get("shots"), events, EventQuery(half=1)).value == 1
    assert compute(get("shots"), events, EventQuery(half=2)).value == 2
    assert compute(get("shots"), events, EventQuery(minute_from=70)).value == 1


def test_filters_compose_with_and_semantics():
    events = [ev("tackle", team="Home", match_time="50:00"),
              ev("tackle", team="Away", match_time="50:00"),
              ev("tackle", team="Home", match_time="10:00")]

    q = EventQuery(action="tackle", team="Home", half=2)
    assert len(select(events, q)) == 1


def test_multiple_values_per_field():
    events = [ev("tackle"), ev("interception"), ev("pass")]

    assert len(select(events, EventQuery(action=("tackle", "interception")))) == 2


def test_a_goal_counts_however_it_was_phrased():
    """The parser emits both spellings; both are goals and both are shots."""
    as_action = [ev("goal")]
    as_result = [ev("shot", result="scored")]

    for events in (as_action, as_result):
        assert compute(get("goals"), events).value == 1
        assert compute(get("shots"), events).value == 1
        assert compute(get("shots_on_target"), events).value == 1


# --------------------------------------------------------------------------- #
# Spatial predicates
# --------------------------------------------------------------------------- #
def test_thirds_and_channels():
    from analytics.query import channel_of, third_of

    assert third_of(10) == "defensive"
    assert third_of(50) == "middle"
    assert third_of(90) == "final"
    assert channel_of(10) == "left"
    assert channel_of(50) == "central"
    assert channel_of(90) == "right"
    assert third_of(None) is None


def test_progression_is_measured_toward_the_opponent_goal():
    from analytics.query import progression_m

    forward = {"x": 20, "y": 50, "end_x": 60, "end_y": 50}
    backward = {"x": 60, "y": 50, "end_x": 20, "end_y": 50}

    assert progression_m(forward) > 0
    assert progression_m(backward) < 0
    assert progression_m({"x": 20, "y": 50}) is None      # no destination


def test_forward_and_progressive_filters():
    events = [
        ev("pass", x=20, y=50, end_x=70, end_y=50),   # ~52 m gained
        ev("pass", x=70, y=50, end_x=60, end_y=50),   # backward
        ev("pass", x=50, y=50, end_x=52, end_y=50),   # barely forward
    ]

    assert len(select(events, EventQuery(forward_only=True))) == 2
    assert len(select(events, EventQuery(min_progression_m=10))) == 1


def test_into_box_filter():
    events = [ev("pass", end_x=90, end_y=50), ev("pass", end_x=50, end_y=50)]

    assert len(select(events, EventQuery(into_box=True))) == 1


# --------------------------------------------------------------------------- #
# Provenance — the trust gate, extended to metrics
# --------------------------------------------------------------------------- #
def test_coordinate_provenance_defaults_by_source():
    from analytics.query import (PROJECTED, UNKNOWN, ZONE_ESTIMATE,
                                 coordinate_provenance)

    assert coordinate_provenance({"source": "vision", "x": 10}) == PROJECTED
    assert coordinate_provenance({"x": 10}) == ZONE_ESTIMATE
    assert coordinate_provenance({}) == UNKNOWN
    assert coordinate_provenance({"coord_provenance": "measured"}) == "measured"


def test_a_metric_reports_the_weakest_provenance_behind_it():
    """A mean over one zone-estimate and nine measurements is not a measurement."""
    from analytics.query import MEASURED, ZONE_ESTIMATE
    from analytics.registry import Metric, SOURCE_DERIVED, compute

    m = Metric(name="_t", display="t", description="", entity="team",
               category="test", source=SOURCE_DERIVED, query=EventQuery(),
               needs_coordinates=True)
    events = [ev("pass", coord_provenance=MEASURED),
              ev("pass", coord_provenance=ZONE_ESTIMATE)]

    result = compute(m, events)
    assert result.provenance == ZONE_ESTIMATE
    assert "zone" in result.note.lower()


def test_min_provenance_filter_excludes_weaker_coordinates():
    from analytics.query import MEASURED

    events = [ev("pass", coord_provenance="measured", x=1),
              ev("pass", coord_provenance="zone_estimate", x=1)]

    assert len(select(events, EventQuery(min_provenance=MEASURED))) == 1


# --------------------------------------------------------------------------- #
# Aggregations, versioning, catalogue
# --------------------------------------------------------------------------- #
def test_ratio_uses_its_declared_denominator():
    events = [ev("shot", result="on target"), ev("shot", result="missed"),
              ev("shot", result="missed"), ev("shot", result="missed")]

    assert compute(get("shot_accuracy"), events).value == 25.0


def test_ratio_of_nothing_is_zero_not_an_error():
    assert compute(get("shot_accuracy"), []).value == 0.0


def test_per90_refuses_a_meaningless_sample():
    from analytics import per90

    r = compute(get("shots"), [ev("shot")])
    assert per90(r, 90) == 1.0
    assert per90(r, 4) is None          # a rate from four minutes is not a rate


def test_every_metric_is_versioned_and_catalogued():
    cat = A.catalogue()

    assert cat
    for entry in cat:
        assert entry["key"].endswith("@1") or "@" in entry["key"]
        assert entry["description"]
        assert entry["confidence"] in {"high", "indicative", "modelled", "unknown"}


def test_registering_a_duplicate_version_is_refused():
    from analytics.registry import Metric, SOURCE_LOGGED, register

    dup = Metric(name="goals", display="Goals", description="", entity="both",
                 category="shooting", source=SOURCE_LOGGED, query=EventQuery())
    with pytest.raises(ValueError):
        register(dup)


def test_results_carry_their_evidence():
    """A number in a table is a claim; the events behind it are the evidence."""
    events = [ev("goal"), ev("goal"), ev("pass")]

    result = compute(get("goals"), events)
    assert result.value == 2
    assert len(result.clip_anchors) == 2
