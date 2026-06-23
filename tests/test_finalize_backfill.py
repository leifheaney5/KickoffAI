"""Tests for finalize.py and backfill.py against an isolated SQLite library."""

import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_finalize_match(lib_env, sample_events, tmp_path, monkeypatch):
    db, library = lib_env
    monkeypatch.chdir(tmp_path)  # isolate from repo working files
    import finalize

    state = {
        "match_name": "2026-06-10 Hub City FC vs FC Frederick",
        "summary": "Solid win.",
        "competition": "Spring League — Round 12",
        "match_date": "2026-06-10",
        "teams": {"home": {"name": "Hub City FC"},
                  "away": {"name": "FC Frederick"}},
        "lineups": {"Home": {"formation": "4-3-3", "players": []},
                    "Away": {"formation": "", "players": []}},
    }
    slug = finalize.finalize_match(events=sample_events, state=state, notes=[],
                                   clock="45:00 (2nd Half)")
    assert slug == "2026-06-10-hub-city-fc-vs-fc-frederick"

    with db.session() as s:
        m = s.query(db.Match).filter_by(slug=slug).one()
        assert m.home_team == "Hub City FC"
        assert m.competition == "Spring League — Round 12"
        assert m.home_score == 1          # one valid Home goal
        assert len(m.events) == len(sample_events)
        kinds = {mf.kind for mf in m.media}
        assert {"report_pdf", "report_txt", "events_csv", "team_csv",
                "player_csv", "timeline_png"} <= kinds


def test_finalize_composes_name_from_teams(lib_env, sample_events, tmp_path,
                                           monkeypatch):
    db, library = lib_env
    monkeypatch.chdir(tmp_path)
    import finalize
    state = {"match_name": "", "match_date": "2026-06-10",
             "teams": {"home": {"name": "Eagles"}, "away": {"name": "Hawks"}}}
    slug = finalize.finalize_match(events=sample_events, state=state, notes=[])
    with db.session() as s:
        m = s.query(db.Match).filter_by(slug=slug).one()
        assert m.name == "Eagles vs Hawks"


def test_backfill_is_idempotent(lib_env, tmp_path, monkeypatch):
    db, library = lib_env
    reports = tmp_path / "reports"
    reports.mkdir()
    ts = "20260610_205359"
    (reports / f"match_report_{ts}.pdf").write_text("pdf")
    (reports / f"match_report_{ts}.txt").write_text("txt")
    (reports / f"match_timeline_{ts}.png").write_text("png")
    (reports / f"match_data_{ts}.json").write_text(json.dumps([
        {"match_time": "05:40", "team": "Home", "action": "goal",
         "result": "scored"},
        {"match_time": "30:00", "team": "Away", "action": "shot",
         "result": "saved"}]))
    monkeypatch.setenv("KICKOFF_REPORTS_DIR", str(reports))
    import backfill

    created = backfill.backfill_reports(str(reports))
    assert len(created) == 1
    # Re-running imports nothing new.
    assert backfill.backfill_reports(str(reports)) == []

    with db.session() as s:
        m = s.query(db.Match).one()
        assert m.home_score == 1
        assert len(m.events) == 2
        assert len(m.media) == 4
