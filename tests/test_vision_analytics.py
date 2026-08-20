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


def test_team_points_filters_per_frame_unlike_collect_player_points():
    """Documents a real divergence between two 'points for a team' helpers.

    collect_player_points (and so average_positions) backfills the team onto a
    track's earlier sightings; team_points (and so the heatmaps) filters frame
    by frame and drops them. The formation dots and the heatmap are therefore
    computed over different point sets for any track labelled late.
    """
    doc = _stats([
        _frame(0, [_p("a", 10, 10, None)]),
        _frame(1, [_p("a", 20, 20, "Away")]),
    ])
    assert len(analytics.collect_player_points(doc)["a"]["points"]) == 2
    assert len(analytics.team_points(doc, "Away")) == 1


def test_team_points_none_team_returns_everyone():
    doc = _stats([_frame(0, [_p("a", 1, 1, "Home"), _p("b", 2, 2, "Away")])])
    assert analytics.team_points(doc).shape == (2, 2)


def test_team_points_empty_still_has_two_columns():
    """Downstream code indexes [:, 0]; an empty (0,) array would raise."""
    assert analytics.team_points(_stats([]), "Home").shape == (0, 2)


def test_player_points_unknown_id_is_empty_not_an_error():
    assert analytics.player_points(_stats([]), "nobody").shape == (0, 2)


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
            _p("h1", 60, 48, "Home"), _p("h2", 64, 52, "Home"),   # tight, high
            _p("a1", 10, 10, "Away"), _p("a2", 40, 90, "Away"),   # loose, deep
        ]),
    ], space="pitch")
    text = analytics.spatial_summary(doc)
    assert "Home held the more compact shape" in text
    assert "Home had the higher average line" in text
