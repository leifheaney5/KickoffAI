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


def test_build_text_has_key_moments_and_by_half(sample_events):
    data = report._collect(sample_events)
    txt = report.build_text(sample_events, data, "Good.", "31:00", "Demo")
    assert "KEY MOMENTS" in txt
    assert "BY HALF" in txt
    assert "leif@leifheaney.com" in txt  # contact in the header
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


def test_generate_embeds_momentum(sample_events, tmp_path):
    paths = report.generate(events=sample_events, summary="s", clock="90:00",
                            out_dir=str(tmp_path), archive=False,
                            match_name="Demo")
    assert "momentum" in paths and os.path.exists(paths["momentum"])
    txt = open(paths["txt"]).read()
    assert "VISION ANALYSIS" not in txt  # CV section removed
    assert "EVENT TIMELINE" not in txt   # event timeline removed


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
