"""Tests for the report generator + CSV exports (report.py)."""

import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import report


def test_conversion():
    assert report._conversion({"Goals": 1, "Shots": 2}) == 50
    assert report._conversion({"Goals": 0, "Shots": 0}) == 0


def test_events_csv_roundtrip(sample_events):
    out = report.build_events_csv(sample_events)
    rows = list(csv.DictReader(io.StringIO(out)))
    assert len(rows) == len(sample_events)
    assert rows[0]["action"] == "goal"
    assert "raw_text" in rows[0]


def test_team_stats_csv_has_possession_and_conversion(sample_events):
    data = report._collect(sample_events)
    out = report.build_team_stats_csv(data)
    text = out.splitlines()
    assert text[0] == "Stat,Home,Away"
    assert any(r.startswith("Possession %") for r in text)
    assert any(r.startswith("Shot Conversion %") for r in text)
    assert any(r.startswith("Passes") for r in text)


def test_player_stats_csv(sample_events):
    data = report._collect(sample_events)
    rows = list(csv.DictReader(io.StringIO(report.build_player_stats_csv(data))))
    names = {r["Player"] for r in rows}
    assert "#10" in names


def test_build_text_has_efficiency_block(sample_events):
    data = report._collect(sample_events)
    txt = report.build_text(sample_events, data, "Good.", "31:00", "Demo")
    assert "EFFICIENCY & POSSESSION" in txt
    assert "Possession" in txt
    assert "Shot Conversion" in txt


def test_scoring_summary_lists_goals_excludes_denied(sample_events):
    goals = report.scoring_summary(sample_events)
    # One approved goal by #10; the denied goal must be excluded.
    assert len(goals) == 1
    assert goals[0]["team"] == "Home"
    assert goals[0]["player"] == "#10"


def test_player_of_match_picks_scorer(sample_events):
    data = report._collect(sample_events)
    potm = report.player_of_match(data["players"])
    assert potm is not None
    name, block, score = potm
    assert name == "#10"  # goal + on-target shot beats a yellow-carded passer
    assert score > 0


def test_player_of_match_none_without_positive_contributions():
    players = {"#7": {"Team": "Away", "Events": 2, "Goals": 0, "On Target": 0,
                      "Shots": 0, "Saves": 0, "Tackles": 0,
                      "Yellow Cards": 1, "Red Cards": 0}}
    assert report.player_of_match(players) is None


def test_build_text_has_scoring_half_and_potm(sample_events):
    data = report._collect(sample_events)
    txt = report.build_text(sample_events, data, "Good.", "31:00", "Demo")
    assert "SCORING SUMMARY" in txt
    assert "BY HALF" in txt
    assert "PLAYER OF THE MATCH" in txt
    # Per-half goals are bucketed by the stamped clock (the goal was at 05:40).
    assert data["home_halves"]["1st"]["Goals"] == 1


def test_key_moments_tags_goals_and_swings(sample_events):
    import insights as IN
    moments = IN.key_moments(sample_events)
    types = {m["type"] for m in moments}
    assert "goal" in types  # the approved Home goal is tagged
    # sorted by minute and each carries a label + source
    minutes = [m["minute"] for m in moments]
    assert minutes == sorted(minutes)
    assert all(m["label"] and m["source"] in ("audio", "momentum")
               for m in moments)


def test_load_cv_stats_missing_returns_none(tmp_path):
    assert report.load_cv_stats(None) is None
    assert report.load_cv_stats(str(tmp_path / "nope.json")) is None


def test_load_cv_stats_summarizes(tmp_path):
    cv = {
        "tracking_data": {
            "frame_rate_sampled": "10_fps", "coordinate_space": "image",
            "spatial_tracking_frames": [
                {"ball": {"x": 10.0, "y": 5.0}, "players": []},
                {"ball": {"x": None}, "players": []},
            ],
        },
        "statistical_events": {
            "possession_summary": {"team_home_percentage": 60.0,
                                   "team_away_percentage": 40.0},
            "passing_stats": [
                {"passer": "TeamA_trk1", "outcome": "completed"},
                {"passer": "TeamB_trk2", "outcome": "intercepted"},
            ],
        },
    }
    p = tmp_path / "cv.json"
    p.write_text(__import__("json").dumps(cv))
    out = report.load_cv_stats(str(p))
    assert out["frames"] == 2
    assert out["possession"] == (60, 40)
    assert out["ball_detect_pct"] == 50
    assert out["passes_total"] == 2
    assert out["pass_by_team"] == {"Home": 1, "Away": 1}


def test_generate_with_cv_embeds_section(sample_events, tmp_path):
    cv_path = tmp_path / "cv.json"
    cv_path.write_text(__import__("json").dumps({
        "tracking_data": {"frame_rate_sampled": "10_fps",
                          "coordinate_space": "image",
                          "spatial_tracking_frames": [{"ball": {"x": 1.0}}]},
        "statistical_events": {
            "possession_summary": {"team_home_percentage": 55.0,
                                   "team_away_percentage": 45.0},
            "passing_stats": [{"passer": "TeamA_trk1", "outcome": "completed"}],
        },
    }))
    paths = report.generate(events=sample_events, summary="s", clock="90:00",
                            out_dir=str(tmp_path), archive=False,
                            match_name="CV Test", cv_stats_file=str(cv_path))
    txt = open(paths["txt"]).read()
    assert "VISION ANALYSIS (CV)" in txt
    assert "momentum" in paths and os.path.exists(paths["momentum"])


def test_pdf_safe_transliterates():
    assert report._pdf_safe("Round — 9 “x”") == 'Round - 9 "x"'


def test_generate_handles_unicode_summary(sample_events, tmp_path):
    # Em-dash / smart quotes in summary + name must not crash PDF generation.
    paths = report.generate(events=sample_events,
                            summary="Frustrating loss — “no end product”",
                            clock="31:00", out_dir=str(tmp_path), archive=False,
                            match_name="Spring League — Round 11")
    assert os.path.exists(paths["pdf"]) and os.path.getsize(paths["pdf"]) > 0


def test_generate_produces_all_artifacts(sample_events, tmp_path):
    paths = report.generate(events=sample_events, summary="s", clock="31:00",
                            out_dir=str(tmp_path), archive=False,
                            match_name="Test FC vs Demo")
    for key in ("txt", "pdf", "events_csv", "team_csv", "players_csv", "image"):
        assert key in paths, f"missing {key}"
        assert os.path.exists(paths[key]), f"file missing: {paths[key]}"
        assert os.path.getsize(paths[key]) > 0
