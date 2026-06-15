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


def test_generate_produces_all_artifacts(sample_events, tmp_path):
    paths = report.generate(events=sample_events, summary="s", clock="31:00",
                            out_dir=str(tmp_path), archive=False,
                            match_name="Test FC vs Demo")
    for key in ("txt", "pdf", "events_csv", "team_csv", "players_csv", "image"):
        assert key in paths, f"missing {key}"
        assert os.path.exists(paths[key]), f"file missing: {paths[key]}"
        assert os.path.getsize(paths[key]) > 0
