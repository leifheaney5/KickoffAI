#!/usr/bin/env python3
"""Known-answer tests for vision/analytics.py.

Every expected value here is computed by hand, not captured from a run, so the
suite fails when the maths changes rather than when the output changes.

These functions feed the Team Shape page and the analyst context, and had no
coverage before v1.24.0 -- nor had they ever been fed calibrated input.
"""

import json
import math

import numpy as np
import pytest

from vision import analytics


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _stats(frames, space="image"):
    """Wrap frame dicts in the match_stats shape analytics.frames() expects."""
    return {
        "tracking_data": {
            "coordinate_space": space,
            "spatial_tracking_frames": frames,
        }
    }


def _frame(index, players, timestamp=None):
    return {
        "frame_index": index,
        "timestamp": timestamp if timestamp is not None else float(index),
        "players": players,
    }


def _p(pid, x, y, team="Home"):
    return {"id": pid, "x": x, "y": y, "team": team}


# --------------------------------------------------------------------------- #
# Loading / iteration
# --------------------------------------------------------------------------- #
def test_load_stats_round_trips(tmp_path):
    doc = _stats([_frame(0, [_p("a", 1.0, 2.0)])])
    path = tmp_path / "match_stats.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert analytics.load_stats(str(path)) == doc


def test_frames_tolerates_missing_and_null():
    assert analytics.frames({}) == []
    assert analytics.frames({"tracking_data": {}}) == []
    # A run that recorded the key but wrote null must not raise.
    assert analytics.frames(_stats(None)) == []


def test_teams_present_preserves_first_sighting_order_and_dedupes():
    doc = _stats([
        _frame(0, [_p("a", 1, 1, "Away"), _p("b", 2, 2, "Home")]),
        _frame(1, [_p("a", 1, 1, "Away"), _p("c", 3, 3, None)]),
    ])
    assert analytics.teams_present(doc) == ["Away", "Home"]


# --------------------------------------------------------------------------- #
# Point collection
# --------------------------------------------------------------------------- #
def test_collect_player_points_skips_none_coordinates():
    doc = _stats([
        _frame(0, [_p("a", 10, 20)]),
        _frame(1, [_p("a", None, 20)]),
        _frame(2, [_p("a", 10, None)]),
        _frame(3, [_p("a", 30, 40)]),
    ])
    rec = analytics.collect_player_points(doc)["a"]
    assert rec["points"] == [(10.0, 20.0), (30.0, 40.0)]


def test_collect_player_points_backfills_team_from_a_later_frame():
    """Team assignment firms up over a run; the earlier points still count."""
    doc = _stats([
        _frame(0, [_p("a", 10, 10, None)]),
        _frame(1, [_p("a", 20, 20, "Away")]),
    ])
    rec = analytics.collect_player_points(doc)["a"]
    assert rec["team"] == "Away"
    assert len(rec["points"]) == 2


# --------------------------------------------------------------------------- #
# Track-level team resolution
# --------------------------------------------------------------------------- #
def test_track_teams_is_none_until_the_track_is_ever_labelled():
    doc = _stats([_frame(0, [_p("a", 10, 10, None)])])
    assert analytics.track_teams(doc) == {"a": None}


def test_track_teams_majority_beats_one_stray_frame():
    """One mis-clustered frame must not decide a track's side."""
    doc = _stats([
        _frame(0, [_p("a", 10, 10, "Home")]),
        _frame(1, [_p("a", 11, 10, "Away")]),   # blurred crop, wrong colour
        _frame(2, [_p("a", 12, 10, "Home")]),
    ])
    assert analytics.track_teams(doc)["a"] == "Home"


def test_track_teams_tie_goes_to_the_label_seen_first():
    doc = _stats([
        _frame(0, [_p("a", 10, 10, "Away")]),
        _frame(1, [_p("a", 11, 10, "Home")]),
    ])
    assert analytics.track_teams(doc)["a"] == "Away"


def test_team_points_and_average_positions_now_use_the_same_points():
    """The heatmap and the formation dots must not disagree about a track.

    They used to: collect_player_points backfilled the team onto a track's
    earlier sightings, team_points filtered frame by frame and dropped them, so
    a player whose colour was only pinned down partway through the run appeared
    in the formation with three frames of history and in the heatmap with one.
    Both now select on the track's resolved team.
    """
    doc = _stats([
        _frame(0, [_p("a", 10, 10, None)]),
        _frame(1, [_p("a", 20, 10, "Away")]),
        _frame(2, [_p("a", 30, 10, "Away")]),
    ])
    heat = analytics.team_points(doc, "Away")
    (dot,) = analytics.average_positions(doc, team="Away", min_frames=3)
    assert len(heat) == dot["n"] == 3
    assert heat[:, 0].mean() == pytest.approx(dot["x"])


def test_team_shape_series_counts_a_player_before_his_colour_was_pinned():
    """Frame 0 has two players on the pitch even if one is not labelled yet."""
    doc = _stats([
        _frame(0, [_p("a", 20, 50, None), _p("b", 60, 50, "Home")]),
        _frame(1, [_p("a", 20, 50, "Home"), _p("b", 60, 50, "Home")]),
    ])
    rows = analytics.team_shape_series(doc, "Home")
    assert [r["n"] for r in rows] == [2, 2]
    assert rows[0]["centroid_x"] == pytest.approx(40.0)


def test_team_points_none_team_returns_everyone():
    doc = _stats([_frame(0, [_p("a", 1, 1, "Home"), _p("b", 2, 2, "Away")])])
    assert analytics.team_points(doc).shape == (2, 2)


def test_team_points_empty_still_has_two_columns():
    """Downstream code indexes [:, 0]; an empty (0,) array would raise."""
    assert analytics.team_points(_stats([]), "Home").shape == (0, 2)


def test_player_points_unknown_id_is_empty_not_an_error():
    assert analytics.player_points(_stats([]), "nobody").shape == (0, 2)


# --------------------------------------------------------------------------- #
# What counts as a usable position
#
# One filter, used by every consumer in the module. The interesting cases only
# become reachable once a homography is in play: an uncalibrated run divides
# pixels by the frame size and so cannot leave 0..100 at all.
# --------------------------------------------------------------------------- #
def test_usable_xy_keeps_a_position_just_off_the_pitch():
    """A throw-in taker is off the pitch and still where he really is."""
    assert analytics.usable_xy(_p("a", 105.0, -4.0)) == (105.0, -4.0)


def test_usable_xy_rejects_a_projection_from_beyond_the_horizon():
    """A crowd detection lands hundreds of pitch-lengths away, not just outside."""
    assert analytics.usable_xy(_p("a", 8400.0, 50.0)) is None
    assert analytics.usable_xy(_p("a", 50.0, -1e6)) is None


def test_usable_xy_rejects_nan_and_infinity():
    assert analytics.usable_xy(_p("a", float("nan"), 50.0)) is None
    assert analytics.usable_xy(_p("a", 50.0, float("inf"))) is None


def test_usable_xy_needs_both_coordinates():
    assert analytics.usable_xy(_p("a", 50.0, None)) is None
    assert analytics.usable_xy(_p("a", None, 50.0)) is None
    assert analytics.usable_xy({"id": "a"}) is None


def test_one_off_pitch_projection_does_not_poison_the_centroid():
    """The whole point of the filter: one bad point used to take the match with it.

    Without it the mean of [30, 50, 8400] is 2826 and every downstream number --
    centroid, compactness, average position, the analyst's digest -- is nonsense
    for the entire match on the strength of a single frame.
    """
    doc = _stats([
        _frame(0, [_p("a", 30, 50), _p("b", 50, 50), _p("c", 8400, 50)]),
    ])
    (row,) = analytics.team_shape_series(doc, "Home")
    assert row["n"] == 2
    assert row["centroid_x"] == pytest.approx(40.0)


def test_a_nan_coordinate_does_not_nan_the_whole_average():
    doc = _stats([
        _frame(0, [_p("a", 10, 20)]),
        _frame(1, [_p("a", float("nan"), 20)]),
        _frame(2, [_p("a", 30, 20)]),
        _frame(3, [_p("a", 20, 20)]),
    ])
    (row,) = analytics.average_positions(doc, min_frames=3)
    assert row["n"] == 3
    assert row["x"] == pytest.approx(20.0)


def test_team_shape_series_skips_a_record_with_x_but_no_y():
    """This raised TypeError before: only x was checked, then both were read."""
    doc = _stats([
        _frame(0, [_p("a", 20, 50), _p("b", 60, None), _p("c", 60, 50)]),
    ])
    (row,) = analytics.team_shape_series(doc, "Home")
    assert row["n"] == 2


def test_territory_ignores_an_off_pitch_projection():
    doc = _stats([
        _frame(0, [_p("h1", 10, 50, "Home"), _p("h2", 8400, 50, "Home")]),
    ])
    terr = analytics.territory(doc)["Home"]
    assert terr["defensive"] == pytest.approx(1.0)


def test_the_filter_is_inert_on_an_uncalibrated_run():
    """Nothing an uncalibrated run can produce is dropped, so nothing changes.

    Image-space coordinates are pixels over the frame size, so they span 0..100
    plus whatever a detection box overhanging the frame edge adds -- units, not
    orders of magnitude. If this ever fails, the filter has started editing runs
    it was never meant to touch.
    """
    doc = _stats([
        _frame(0, [_p("a", 0.0, 0.0), _p("b", 100.0, 100.0), _p("c", 50.0, 50.0),
                   _p("d", -3.0, 104.0)]),
    ])
    assert len(analytics.team_points(doc, "Home")) == 4


# --------------------------------------------------------------------------- #
# Direction helpers
# --------------------------------------------------------------------------- #
def test_is_advancing_flips_for_away_and_with_the_flag():
    assert analytics.is_advancing("Home", True) is True
    assert analytics.is_advancing("Away", True) is False
    assert analytics.is_advancing("Home", False) is False
    assert analytics.is_advancing("Away", False) is True


def test_attack_relative_measures_from_the_team_s_own_end():
    assert analytics.attack_relative(80.0, advancing=True) == pytest.approx(80.0)
    assert analytics.attack_relative(80.0, advancing=False) == pytest.approx(20.0)


# --------------------------------------------------------------------------- #
# Heatmap
# --------------------------------------------------------------------------- #
def test_heatmap_empty_returns_zero_grid_with_correct_edges():
    H, xe, ye = analytics.heatmap([], bins=(4, 2))
    assert H.shape == (4, 2)
    assert not H.any()
    assert len(xe) == 5 and len(ye) == 3
    assert xe[0] == 0 and xe[-1] == 100


def test_heatmap_is_x_major_not_image_order():
    """H[i_x, i_y] -- the docstring promises this and the pages transpose it."""
    H, _, _ = analytics.heatmap([(90.0, 10.0)], bins=(2, 2), normalize=False)
    assert H[1, 0] == 1.0
    assert H.sum() == 1.0


def test_heatmap_normalize_scales_by_the_peak():
    pts = [(10.0, 10.0)] * 3 + [(90.0, 90.0)]
    H, _, _ = analytics.heatmap(pts, bins=(2, 2), normalize=True)
    assert H.max() == pytest.approx(1.0)
    assert H[1, 1] == pytest.approx(1 / 3)


def test_heatmap_drops_points_outside_the_pitch_range():
    """Uncalibrated runs can put a box centre off-pitch; it must not wrap."""
    H, _, _ = analytics.heatmap(
        [(50.0, 50.0), (150.0, 50.0), (-10.0, 50.0)], bins=(2, 2), normalize=False
    )
    assert H.sum() == 1.0


def test_heatmap_accepts_an_ndarray_as_well_as_a_list():
    H, _, _ = analytics.heatmap(np.array([[50.0, 50.0]]), bins=(2, 2), normalize=False)
    assert H.sum() == 1.0


# --------------------------------------------------------------------------- #
# Average positions (formation)
# --------------------------------------------------------------------------- #
def test_average_positions_drops_tracks_below_min_frames():
    doc = _stats([
        _frame(0, [_p("keep", 10, 10), _p("blip", 90, 90)]),
        _frame(1, [_p("keep", 20, 10)]),
        _frame(2, [_p("keep", 30, 10)]),
    ])
    out = analytics.average_positions(doc, min_frames=3)
    assert [r["id"] for r in out] == ["keep"]


def test_average_positions_exact_mean_and_spread():
    doc = _stats([
        _frame(0, [_p("a", 10, 20)]),
        _frame(1, [_p("a", 30, 20)]),
        _frame(2, [_p("a", 20, 20)]),
    ])
    (row,) = analytics.average_positions(doc, min_frames=3)
    assert row["x"] == pytest.approx(20.0)
    assert row["y"] == pytest.approx(20.0)
    assert row["n"] == 3
    # population std of [10,30,20] = sqrt(200/3); y std is 0, so spread == x std
    assert row["spread"] == pytest.approx(math.sqrt(200 / 3))


def test_average_positions_single_sighting_has_zero_spread_not_nan():
    """min_frames=1 admits a one-point track; its std is 0, not a divide."""
    doc = _stats([_frame(0, [_p("a", 42.0, 17.0)])])
    (row,) = analytics.average_positions(doc, min_frames=1)
    assert row["n"] == 1
    assert (row["x"], row["y"]) == (42.0, 17.0)
    assert row["spread"] == 0.0


def test_team_shape_series_zero_spread_is_zero():
    """Everyone stacked on one point: compactness 0, both spreads 0."""
    doc = _stats([_frame(0, [_p("a", 50, 50), _p("b", 50, 50), _p("c", 50, 50)])])
    (row,) = analytics.team_shape_series(doc, "Home")
    assert row["compactness"] == 0.0
    assert row["spread_length"] == 0.0
    assert row["spread_width"] == 0.0


def test_average_positions_team_filter_uses_the_backfilled_team():
    doc = _stats([
        _frame(0, [_p("a", 10, 10, None)]),
        _frame(1, [_p("a", 20, 10, "Away")]),
        _frame(2, [_p("a", 30, 10, "Away")]),
    ])
    (row,) = analytics.average_positions(doc, team="Away", min_frames=3)
    assert row["n"] == 3
    assert row["x"] == pytest.approx(20.0)


# --------------------------------------------------------------------------- #
# Team shape
# --------------------------------------------------------------------------- #
def test_team_shape_series_needs_at_least_two_players_in_frame():
    doc = _stats([
        _frame(0, [_p("a", 10, 10)]),
        _frame(1, [_p("a", 10, 10), _p("b", 20, 20)]),
    ])
    rows = analytics.team_shape_series(doc, "Home")
    assert [r["frame"] for r in rows] == [1]


def test_team_shape_series_exact_geometry():
    doc = _stats([_frame(7, [_p("a", 20, 40), _p("b", 60, 60)], timestamp=1.5)])
    (row,) = analytics.team_shape_series(doc, "Home")
    assert row["frame"] == 7 and row["timestamp"] == 1.5 and row["n"] == 2
    assert row["centroid_x"] == pytest.approx(40.0)
    assert row["centroid_y"] == pytest.approx(50.0)
    assert row["spread_length"] == pytest.approx(20.0)   # std of [20, 60]
    assert row["spread_width"] == pytest.approx(10.0)    # std of [40, 60]
    # both players sit hypot(20, 10) from the centroid
    assert row["compactness"] == pytest.approx(math.hypot(20.0, 10.0))


def test_team_shape_series_ignores_the_other_team():
    doc = _stats([_frame(0, [_p("a", 10, 10, "Home"), _p("b", 90, 90, "Away")])])
    assert analytics.team_shape_series(doc, "Home") == []


def test_team_shape_summary_is_none_without_usable_frames():
    assert analytics.team_shape_summary(_stats([]), "Home") is None


def test_team_shape_summary_averages_across_frames():
    doc = _stats([
        _frame(0, [_p("a", 0, 50), _p("b", 20, 50)]),    # centroid_x 10
        _frame(1, [_p("a", 30, 50), _p("b", 50, 50)]),   # centroid_x 40
    ])
    summ = analytics.team_shape_summary(doc, "Home")
    assert summ["frames"] == 2
    assert summ["avg_players"] == pytest.approx(2.0)
    assert summ["centroid_x"] == pytest.approx(25.0)
    assert summ["compactness"] == pytest.approx(10.0)


# --------------------------------------------------------------------------- #
# Territory
# --------------------------------------------------------------------------- #
def test_territory_is_attack_relative_and_mirrors_for_away():
    """The same physical x is attacking for Home and defensive for Away."""
    doc = _stats([_frame(0, [_p("h", 80, 50, "Home"), _p("a", 80, 50, "Away")])])
    terr = analytics.territory(doc, home_attacks_positive_x=True)
    assert terr["Home"]["attacking"] == pytest.approx(1.0)
    assert terr["Away"]["defensive"] == pytest.approx(1.0)


def test_territory_respects_the_direction_flag():
    doc = _stats([_frame(0, [_p("h", 80, 50, "Home")])])
    terr = analytics.territory(doc, home_attacks_positive_x=False)
    assert terr["Home"]["defensive"] == pytest.approx(1.0)


def test_territory_thirds_sum_to_one_per_team():
    doc = _stats([
        _frame(0, [_p("h1", 10, 50, "Home"), _p("h2", 50, 50, "Home"),
                   _p("h3", 90, 50, "Home")]),
    ])
    terr = analytics.territory(doc)["Home"]
    assert sum(terr.values()) == pytest.approx(1.0)
    assert terr["defensive"] == pytest.approx(1 / 3)
    assert terr["middle"] == pytest.approx(1 / 3)
    assert terr["attacking"] == pytest.approx(1 / 3)


def test_territory_ignores_unlabelled_and_unknown_teams():
    doc = _stats([_frame(0, [_p("x", 90, 50, None), _p("y", 90, 50, "Referee")])])
    terr = analytics.territory(doc)
    # No player counted anywhere; the zero-guard must not divide by zero.
    assert sum(terr["Home"].values()) == pytest.approx(0.0)
    assert sum(terr["Away"].values()) == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Hotspot zones
# --------------------------------------------------------------------------- #
def test_hotspot_zone_is_none_when_there_are_no_points():
    assert analytics.hotspot_zone([], advancing=True) is None


def test_hotspot_zone_thirds_are_attack_relative():
    pts = [(90.0, 50.0)] * 5
    assert analytics.hotspot_zone(pts, advancing=True).startswith("attacking third")
    assert analytics.hotspot_zone(pts, advancing=False).startswith("defensive third")


def test_hotspot_zone_lateral_is_also_attack_relative():
    """A team attacking the other way has its left and right swapped too.

    Thirds already flip with `advancing`; the flank label has to flip with it or
    the label mixes a team-relative third with an absolute touchline.
    """
    pts = [(90.0, 10.0)] * 5
    assert analytics.hotspot_zone(pts, advancing=True) == "attacking third / left"
    assert analytics.hotspot_zone(pts, advancing=False) == "defensive third / right"


def test_hotspot_zone_works_from_a_single_point():
    """A 3x3 grid with one occupied cell still has an unambiguous argmax."""
    assert analytics.hotspot_zone([(10.0, 90.0)], advancing=True) == (
        "defensive third / right"
    )


def test_hotspot_zone_is_none_when_every_point_is_off_pitch():
    assert analytics.hotspot_zone([(8400.0, 50.0)], advancing=True) is None


def test_hotspot_zone_central_band_is_unaffected_by_direction():
    pts = [(50.0, 50.0)] * 5
    assert analytics.hotspot_zone(pts, advancing=True).endswith("/ central")
    assert analytics.hotspot_zone(pts, advancing=False).endswith("/ central")


# --------------------------------------------------------------------------- #
# Narrative digest
# --------------------------------------------------------------------------- #
def test_spatial_summary_warns_loudly_when_uncalibrated():
    doc = _stats([_frame(0, [_p("a", 10, 10), _p("b", 20, 20)])], space="image")
    text = analytics.spatial_summary(doc)
    assert "UNCALIBRATED" in text


def test_spatial_summary_drops_the_warning_once_calibrated():
    doc = _stats([_frame(0, [_p("a", 10, 10), _p("b", 20, 20)])], space="pitch")
    assert "UNCALIBRATED" not in analytics.spatial_summary(doc)


def test_spatial_summary_handles_an_empty_run_without_raising():
    text = analytics.spatial_summary(_stats([]))
    assert "0 sampled frames" in text


def test_spatial_summary_compares_the_two_teams():
    doc = _stats([
        _frame(0, [
            _p("h1", 60, 48, "Home"), _p("h2", 64, 52, "Home"),   # tight
            _p("a1", 10, 10, "Away"), _p("a2", 40, 90, "Away"),   # loose
        ]),
    ], space="pitch")
    text = analytics.spatial_summary(doc)
    assert "Home held the more compact shape" in text
    # Home's centroid x is 62, Away's is 25, and Away attacks towards x=0 -- so
    # Away sits 75 up the pitch from its own goal line against Home's 62. Away
    # has the higher line despite the smaller x.
    assert "Away had the higher average line" in text


def test_spatial_summary_higher_line_is_not_just_the_bigger_x():
    """The absolute-vs-relative bug, isolated.

    Both teams are camped on the same touchline half. Home (attacking x=100)
    averages x=30, so it is 30 up the pitch. Away (attacking x=0) averages
    x=20, so it is 80 up the pitch and has much the higher line. Comparing raw
    centroid_x picks Home, which is the deeper of the two.
    """
    doc = _stats([
        _frame(0, [
            _p("h1", 20, 50, "Home"), _p("h2", 40, 50, "Home"),   # centroid x 30
            _p("a1", 10, 50, "Away"), _p("a2", 30, 50, "Away"),   # centroid x 20
        ]),
    ], space="pitch")
    assert "Away had the higher average line" in analytics.spatial_summary(doc)


def test_spatial_summary_reports_position_attack_relative():
    """Away's centroid x=25 is reported as 75 up-pitch, matching its territory."""
    doc = _stats([
        _frame(0, [_p("a1", 20, 40, "Away"), _p("a2", 30, 40, "Away")]),
    ], space="pitch")
    text = analytics.spatial_summary(doc)
    assert "avg position 75 up-pitch / 60 across" in text


def test_spatial_summary_survives_a_team_of_identical_points():
    """Zero spread everywhere: no divide, no NaN, and the digest still renders."""
    doc = _stats([
        _frame(0, [_p("a", 50, 50), _p("b", 50, 50), _p("c", 50, 50)]),
    ], space="pitch")
    text = analytics.spatial_summary(doc)
    assert "compactness 0.0" in text
    assert "nan" not in text.lower()


def test_spatial_summary_survives_a_single_tracked_player():
    """One player has no shape, so there is no team line -- but no crash either."""
    doc = _stats([_frame(0, [_p("a", 50, 50)])], space="pitch")
    text = analytics.spatial_summary(doc)
    assert "1 tracked player-ids" in text
    assert "Home:" not in text
