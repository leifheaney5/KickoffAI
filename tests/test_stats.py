"""Tests for the stat engine (stats.py)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stats as S


def test_aggregate_counts(sample_events):
    home = S.team_stats(sample_events, "Home")
    # One goal (the denied one is excluded). A goal also counts as a shot + OT.
    assert home["Goals"] == 1
    assert home["Shots"] == 2          # explicit shot + the goal
    assert home["On Target"] == 2      # on-target shot + the goal
    assert home["Tackles"] == 1
    assert home["Passes"] == 0


def test_aggregate_cards_and_passes(sample_events):
    away = S.team_stats(sample_events, "Away")
    assert away["Yellow Cards"] == 1
    assert away["Red Cards"] == 0
    assert away["Passes"] == 1
    assert away["Goals"] == 0


def test_denied_events_excluded(sample_events):
    # The denied Home goal must not inflate the score.
    assert S.team_stats(sample_events, "Home")["Goals"] == 1


def test_passes_in_stat_keys():
    assert "Passes" in S.STAT_KEYS


def test_possession_empty_is_5050():
    assert S.possession({}, {}) == (50, 50)


def test_possession_sums_to_100(sample_events):
    home = S.team_stats(sample_events, "Home")
    away = S.team_stats(sample_events, "Away")
    hp, ap = S.possession(home, away)
    assert hp + ap == 100
    assert 0 <= hp <= 100


def test_possession_favors_more_on_ball():
    home = {"Passes": 10, "Shots": 2, "Corners": 1, "On Target": 1, "Goals": 1}
    away = {"Passes": 0, "Shots": 0, "Corners": 0, "On Target": 0, "Goals": 0}
    hp, ap = S.possession(home, away)
    assert hp == 100 and ap == 0


def test_player_stats(sample_events):
    players = S.player_stats(sample_events)
    assert "#10" in players
    assert players["#10"]["Team"] == "Home"
    assert players["#10"]["Goals"] == 1


def test_pop_last_event(tmp_path):
    path = str(tmp_path / "match_data.json")
    S.save_events([{"timestamp": "a", "action": "pass"},
                   {"timestamp": "b", "action": "goal"}], path)
    removed = S.pop_last_event(path)
    assert removed["timestamp"] == "b"
    assert len(S.load_events(path)) == 1
    # Popping down to empty, then once more, returns None.
    S.pop_last_event(path)
    assert S.pop_last_event(path) is None


def test_delete_and_update_event(tmp_path):
    path = str(tmp_path / "match_data.json")
    S.save_events([{"timestamp": "x", "action": "pass"}], path)
    assert S.update_event("x", {"action": "shot"}, path) is True
    assert S.load_events(path)[0]["action"] == "shot"
    assert S.delete_event("x", path) is True
    assert S.load_events(path) == []
