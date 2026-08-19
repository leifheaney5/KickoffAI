"""Tests for the taxonomy, the xG model, and the derived metrics.

The xG tests pin the model against published open-data baselines, because the
first version of these coefficients gave a central penalty-box shot 0.70 — a
penalty-level number that any coach would have known was wrong.

The derived-metric tests pin the honesty floors: a metric with no evidence must
report nothing, not zero.
"""

import math

import pytest

from analytics import derived_metrics as D
from football import taxonomy as T
from models import xg as XG


def shot(**kw):
    e = {"action": "shot", "team": "Home", "match_time": "10:00",
         "status": "pending"}
    e.update(kw)
    return e


# --------------------------------------------------------------------------- #
# Taxonomy
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("said,canonical", [
    ("shoots", "shot"), ("scores", "goal"), ("booked", "yellow_card"),
    ("sent off", "red_card"), ("won the ball", "recovery"),
    ("nutmeg", "take_on"), ("intercepted", "interception"),
    ("free kick", "free_kick"), ("pass", "pass"),
])
def test_synonyms_collapse_to_one_canonical_action(said, canonical):
    """A model says the same thing three ways; the mapping belongs in code."""
    assert T.canonical_action(said) == canonical


def test_an_unknown_action_is_refused():
    assert T.canonical_action("wibble") is None
    assert T.canonical_action(None) is None


@pytest.mark.parametrize("said,part", [
    ("header", "head"), ("with his head", "head"), ("left foot", "left_foot"),
    ("right", "right_foot"), ("chest", "other"),
])
def test_body_part_synonyms(said, part):
    assert T.canonical_body_part(said) == part


@pytest.mark.parametrize("said,outcome", [
    ("on target", "on_target"), ("wide", "off_target"),
    ("hit the post", "woodwork"), ("saved", "saved"), ("scored", "scored"),
])
def test_shot_outcome_synonyms(said, outcome):
    assert T.canonical_shot_outcome(said) == outcome


def test_normalise_is_non_destructive():
    """A reviewer must still see exactly what was said."""
    e = shot(action="shoots", result="wide", raw_text="home nine shoots wide")

    out = T.normalise(e)

    assert out["action"] == "shoots"          # original preserved
    assert out["action_canonical"] == "shot"
    assert out["shot_outcome"] == "off_target"


def test_normalise_invents_nothing():
    out = T.normalise(shot())

    assert "body_part" not in out             # absent means unknown, not "foot"


def test_body_part_can_be_recovered_from_the_phrasing():
    out = T.normalise(shot(raw_text="home nine with a header from the corner"))

    assert out["body_part"] == "head"


def test_the_taxonomy_is_much_larger_than_the_old_vocabulary():
    assert len(T.ACTIONS) > 40                # was 13


# --------------------------------------------------------------------------- #
# xG — pinned to published baselines
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("distance_m,expected,tol", [
    (6.0, 0.45, 0.09),
    (11.0, 0.20, 0.06),
    (16.5, 0.08, 0.04),
    (25.0, 0.03, 0.03),
])
def test_central_shots_track_open_data_baselines(distance_m, expected, tol):
    """The regression that mattered: a box shot must not read like a penalty."""
    x = 100.0 - (distance_m / 105.0 * 100.0)

    got = XG.estimate(shot(x=x, y=50.0))["xg"]

    assert abs(got - expected) < tol, f"{distance_m}m gave {got}, want ~{expected}"


def test_xg_falls_with_distance_and_with_angle():
    close = XG.estimate(shot(x=95, y=50))["xg"]
    far = XG.estimate(shot(x=70, y=50))["xg"]
    tight = XG.estimate(shot(x=95, y=8))["xg"]

    assert close > far
    assert close > tight            # same distance band, worse angle


def test_headers_convert_worse_than_feet_at_equal_geometry():
    foot = XG.estimate(shot(x=91.5, y=50, body_part="right foot"))["xg"]
    head = XG.estimate(shot(x=91.5, y=50, body_part="header"))["xg"]

    assert head < foot


def test_penalties_bypass_geometry():
    e = XG.estimate(shot(action="penalty"))

    assert e["xg"] == XG.PENALTY_XG
    assert e["provenance"] == "rule"
    assert "geometry" in e["note"]


def test_a_shot_with_no_location_says_so():
    e = XG.estimate(shot())

    assert e["provenance"] == "no_geometry"
    assert "no shot location" in e["note"].lower()


def test_zone_estimated_shots_carry_their_caveat():
    e = XG.estimate(shot(x=91.5, y=50, coord_provenance="zone_estimate"))

    assert e["provenance"] == "zone_estimate"
    assert "zone" in e["note"].lower()


def test_xg_is_bounded():
    assert 0 < XG.estimate(shot(x=99.9, y=50))["xg"] <= 0.99
    assert XG.estimate(shot(x=1, y=1))["xg"] >= 0.01


def test_non_shots_get_no_xg():
    assert XG.estimate({"action": "tackle"}) is None


def test_the_model_card_states_it_is_not_fitted():
    card = XG.model_card()

    assert "not fitted" in card["fitted_on"].lower()
    assert "model, not a measurement" in card["caveat"].lower()
    assert card["coefficients"]["distance"] < 0     # further is worse


def test_team_xg_reports_the_weakest_provenance():
    events = [shot(x=91.5, y=50, coord_provenance="measured"),
              shot()]                                # no location at all

    assert XG.team_xg(events, "Home")["provenance"] == "no_geometry"


# --------------------------------------------------------------------------- #
# Derived metrics — the honesty floors
# --------------------------------------------------------------------------- #
def test_ppda_reports_nothing_rather_than_zero_without_evidence():
    """0.0 would read as the most aggressive press ever recorded."""
    events = [{"action": "tackle", "team": "Home", "match_time": "10:00"}]

    result = D.ppda(events, "Home", "Away")

    assert result["ppda"] is None
    assert result["unavailable"]


def test_ppda_exposes_its_numerator_and_denominator():
    events = ([{"action": "pass", "team": "Away", "match_time": f"{i}:00"}
               for i in range(10, 25)]
              + [{"action": "tackle", "team": "Home", "match_time": "30:00"}] * 5)

    result = D.ppda(events, "Home", "Away")

    assert result["ppda"] == pytest.approx(15 / 5)
    assert result["opponent_passes"] == 15
    assert result["defensive_actions"] == 5
    assert "divided by" in result["definition"]


def test_field_tilt_stays_silent_on_a_tiny_sample():
    events = [{"action": "pass", "team": "Home", "x": 90, "match_time": "10:00"}]

    assert D.field_tilt(events, "Home", "Away") is None


def test_field_tilt_measures_final_third_share():
    events = ([{"action": "pass", "team": "Home", "x": 90, "match_time": "10:00"}] * 9
              + [{"action": "pass", "team": "Away", "x": 90, "match_time": "11:00"}] * 3)

    assert D.field_tilt(events, "Home", "Away") == 75.0


def test_match_summary_runs_end_to_end_on_a_sparse_log():
    """The real match log is sparse; nothing here may crash on it."""
    events = [shot(location="box"), {"action": "tackle", "team": "Away",
                                     "match_time": "20:00"}]

    summary = D.match_summary(events)

    assert set(summary) == {"Home", "Away"}
    assert summary["Home"]["expected_goals"]["shots"] == 1
    # The bridged "box" gives real geometry rather than the no-location fallback.
    assert summary["Home"]["expected_goals"]["provenance"] == "zone_estimate"


# --------------------------------------------------------------------------- #
# The producer side — the Ear and Manual Entry must be able to emit what the
# analytics can measure. The taxonomy existed for a release while the parser
# still offered thirteen actions, so the app could measure far more than it
# could ever capture.
# --------------------------------------------------------------------------- #
def test_the_parser_is_offered_the_whole_taxonomy():
    import audio_tracker as A

    offered = A._prompt_actions()

    for action in ("recovery", "take_on", "aerial_duel", "through_ball",
                   "sweeper_action", "handball"):
        assert action in offered, f"{action} missing from the parser vocabulary"


def test_the_prompt_asks_for_the_fields_xg_needs():
    import audio_tracker as A

    prompt = A.SYSTEM_PROMPT

    assert "body_part" in prompt
    assert "play_pattern" in prompt
    assert "big_chance" in prompt
    # Shot location is the field that most improves the analysis.
    assert "location" in prompt and "shot" in prompt.lower()


def test_the_prompt_forbids_guessing():
    """A fabricated body part would silently skew every xG built on it."""
    import audio_tracker as A

    assert "NEVER" in A.SYSTEM_PROMPT
    assert "ONLY if" in A.SYSTEM_PROMPT


def test_an_event_carries_the_qualifier_fields():
    import audio_tracker as A

    assert set(A._empty_event()) >= {"body_part", "play_pattern", "big_chance"}


def test_ingest_canonicalises_without_destroying_what_was_said():
    import audio_tracker as A

    e = A.resolve_event({"team": "Home", "player": "number 9",
                         "action": "shoots", "result": "wide",
                         "location": "edge of the box"})

    assert e["action"] == "shoots"              # the speaker's word survives
    assert e["action_canonical"] == "shot"      # and the taxonomy's form is added
    assert e["shot_outcome"] == "off_target"


def test_ingest_invents_nothing_for_unstated_fields():
    import audio_tracker as A

    e = A.resolve_event({"team": "Home", "action": "shot"})

    assert e["body_part"] is None
    assert e["play_pattern"] is None


def test_a_richer_event_produces_a_real_xg_rather_than_the_fallback():
    """The point of the whole exercise, end to end."""
    import audio_tracker as A
    from football.zones import enrich
    from models import xg as XG

    plain = A.resolve_event({"team": "Home", "action": "shot"})
    detailed = A.resolve_event({"team": "Home", "action": "shot",
                                "location": "box", "body_part": "head",
                                "play_pattern": "corner"})

    plain_xg = XG.estimate(enrich(plain))
    detailed_xg = XG.estimate(enrich(detailed))

    assert plain_xg["provenance"] == "no_geometry"      # a flat average
    assert detailed_xg["provenance"] == "zone_estimate"  # an actual estimate
    assert detailed_xg["xg"] != plain_xg["xg"]
    # Header from a corner: worse than a plain box shot at the same geometry.
    assert detailed_xg["factors"]["body_part"] < 1.0
