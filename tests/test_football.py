"""Tests for the coordinate bridge and the possession/sequence engines.

The zone bridge is asserted to *refuse* as carefully as it resolves: the real
match log contains "utah, iowa" from a mis-transcription, and inventing a pitch
position for it would quietly corrupt every spatial metric built on top.
"""

import pytest

from football import possessions as P
from football.zones import ZoneEstimate, enrich, enrich_all, resolve


def ev(action=None, team="Home", minute="10:00", **extra):
    e = {"action": action, "team": team, "match_time": minute,
         "status": "pending"}
    e.update(extra)
    return e


# --------------------------------------------------------------------------- #
# The coordinate bridge
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("phrase,label", [
    ("box", "penalty_box"),
    ("in the box", "penalty_box"),
    ("penalty area", "penalty_box"),
    ("18 yard box", "penalty_box"),
    ("six yard box", "six_yard_box"),
    ("edge of the box", "zone_14"),
    ("own box", "own_box"),
    ("halfway line", "halfway"),
])
def test_named_areas_pin_both_axes(phrase, label):
    est = resolve(phrase)

    assert est is not None and est.label == label
    assert est.confidence == "area"


def test_bare_box_resolves__the_commonest_phrasing_in_real_logs():
    """It is the most frequent location in the real match log."""
    est = resolve("box")

    assert est is not None
    assert est.x > 83          # inside the penalty area
    assert est.confidence == "area"


@pytest.mark.parametrize("phrase", ["utah, iowa", "somewhere", "", None, "   ",
                                    "!!!"])
def test_unrecognised_phrases_are_refused_not_guessed(phrase):
    """Refusing is the point: a fabricated position corrupts everything above."""
    assert resolve(phrase) is None


def test_partial_descriptions_stay_partial():
    """"Left wing" fixes the channel and says nothing about the third."""
    est = resolve("left wing")

    assert est is not None
    assert est.confidence == "partial"
    assert est.y < 33                    # left channel
    assert est.x == pytest.approx(50)    # third unstated, filled from the middle


def test_a_fully_described_place_is_not_partial():
    est = resolve("final third left wing")

    assert est.confidence == "area"
    assert est.x > 66 and est.y < 33


def test_own_half_and_their_half_point_opposite_ways():
    ours, theirs = resolve("our half"), resolve("their half")

    assert ours.x < 50 < theirs.x


def test_enrich_tags_provenance_and_never_claims_measurement():
    out = enrich(ev("shot", location="box"))

    assert out["coord_provenance"] == "zone_estimate"
    assert out["x"] > 83


def test_enrich_never_overwrites_real_coordinates():
    """Vision-measured positions outrank a described one, always."""
    measured = ev("shot", location="box", x=12.0, y=34.0,
                  coord_provenance="measured")

    assert enrich(measured) == measured


def test_enrich_leaves_unmappable_events_alone():
    out = enrich(ev("shot", location="utah, iowa"))

    assert "x" not in out
    assert out["coord_provenance"] if "coord_provenance" in out else True


def test_enrich_all_is_idempotent():
    once = enrich_all([ev("shot", location="box")])
    twice = enrich_all(once)

    assert once == twice


# --------------------------------------------------------------------------- #
# Possession reconstruction
# --------------------------------------------------------------------------- #
def test_possession_changes_when_the_other_team_acts():
    events = [ev("pass", "Home", "10:00"), ev("pass", "Home", "10:10"),
              ev("pass", "Away", "10:20")]

    poss = P.build(events)

    assert [p.team for p in poss] == ["Home", "Away"]
    assert poss[0].event_count == 2


def test_a_tackle_hands_possession_to_the_tackler():
    events = [ev("pass", "Home", "10:00"),
              ev("tackle", "Away", "10:05"),
              ev("pass", "Away", "10:10")]

    poss = P.build(events)

    assert [p.team for p in poss] == ["Home", "Away"]
    assert poss[1].start_type == "turnover"


def test_a_set_piece_start_is_labelled():
    poss = P.build([ev("corner", "Home", "10:00"), ev("shot", "Home", "10:05")])

    assert poss[0].start_type == "set_piece"


def test_a_long_silence_ends_a_possession():
    """A coach narrating live misses events; a four-minute possession is fiction."""
    events = [ev("pass", "Home", "10:00"), ev("pass", "Home", "14:00")]

    poss = P.build(events)

    assert len(poss) == 2


def test_denied_events_are_excluded():
    events = [ev("pass", "Home", "10:00"),
              dict(ev("goal", "Home", "10:10"), status="denied")]

    poss = P.build(events)

    assert not poss[0].ended_in_goal


def test_unattributed_events_join_the_possession_in_progress():
    """Narration without a team describes the play; it does not start one."""
    events = [ev("pass", "Home", "10:00"), ev("pass", None, "10:05"),
              ev("pass", "Home", "10:10")]

    poss = P.build(events)

    assert len(poss) == 1
    assert poss[0].event_count == 3


def test_possession_outcomes():
    scoring = P.build([ev("pass", "Home", "10:00"),
                       ev("goal", "Home", "10:10")])[0]
    quiet = P.build([ev("pass", "Away", "20:00")])[0]

    assert scoring.ended_in_shot and scoring.ended_in_goal
    assert not quiet.ended_in_shot


def test_progression_uses_bridged_coordinates():
    events = enrich_all([ev("pass", "Home", "10:00", location="our half"),
                         ev("shot", "Home", "10:10", location="box")])

    poss = P.build(events)[0]

    assert poss.progression > 0        # moved toward goal
    assert poss.reached_box is True


def test_summarise_reports_per_team_rates():
    events = [ev("pass", "Home", "10:00"), ev("shot", "Home", "10:05"),
              ev("pass", "Away", "11:00")]

    summary = P.summarise(events)

    assert summary["Home"]["possessions"] == 1
    assert summary["Home"]["with_shot"] == 1
    assert summary["Home"]["shot_rate"] == 100.0
    assert summary["Away"]["with_shot"] == 0


def test_build_is_deterministic():
    events = [ev("pass", "Home", "10:00"), ev("tackle", "Away", "10:05"),
              ev("corner", "Away", "10:20"), ev("goal", "Away", "10:30")]

    assert ([(p.team, p.event_count) for p in P.build(events)]
            == [(p.team, p.event_count) for p in P.build(events)])


# --------------------------------------------------------------------------- #
# Sequences
# --------------------------------------------------------------------------- #
def test_a_restart_splits_a_possession_into_sequences():
    poss = P.build([ev("pass", "Home", "10:00"),
                    ev("pass", "Home", "10:05")])[0]
    poss.events.append(ev("throw_in", "Home", "10:20"))
    poss.events.append(ev("pass", "Home", "10:25"))

    seqs = P.sequences(poss)

    assert len(seqs) == 2


def test_sequence_classification_uses_arguments_not_magic_numbers():
    poss = P.build([ev("pass", "Home", f"10:{i:02d}") for i in range(0, 60, 10)])[0]
    seq = P.sequences(poss)[0]

    assert seq.classify(sustained_passes=3) == "SUSTAINED_POSSESSION"
    assert seq.classify(sustained_passes=99) != "SUSTAINED_POSSESSION"


def test_directness_is_none_without_coordinates():
    poss = P.build([ev("pass", "Home", "10:00"), ev("pass", "Home", "10:05")])[0]

    assert P.sequences(poss)[0].directness is None
