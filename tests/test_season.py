"""Tests for cross-match season aggregation (season.py)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import season


def _matches():
    return [
        {"home_team": "Eagles", "away_team": "Hawks",
         "home_score": 2, "away_score": 1},   # Eagles win
        {"home_team": "Hawks", "away_team": "Eagles",
         "home_score": 0, "away_score": 0},   # draw
        {"home_team": "Eagles", "away_team": "Owls",
         "home_score": 3, "away_score": 0},   # Eagles win
        {"home_team": "", "away_team": "Owls",
         "home_score": 1, "away_score": 1},   # skipped (missing name)
    ]


def test_standings_points_and_order():
    table = season.team_standings(_matches())
    top = table[0]
    assert top["team"] == "Eagles"
    assert top["Pts"] == 7        # two wins + one draw
    assert top["P"] == 3
    assert top["GF"] == 5 and top["GA"] == 1 and top["GD"] == 4


def test_standings_skips_missing_team():
    table = season.team_standings(_matches())
    # The match with a blank home_team must not create an empty-named row, and
    # Owls only get their one valid match.
    owls = next(r for r in table if r["team"] == "Owls")
    assert owls["P"] == 1


def test_top_scorers_counts_and_skips_unnamed():
    goals = [
        {"player": "#10", "team": "Eagles"},
        {"player": "#10", "team": "Eagles"},
        {"player": "#9", "team": "Hawks"},
        {"player": None, "team": "Eagles"},   # skipped
    ]
    scorers = season.top_scorers(goals)
    assert scorers[0] == {"player": "#10", "team": "Eagles", "goals": 2}
    assert all(s["player"] for s in scorers)
    assert len(scorers) == 2
