"""Shared pytest fixtures for Kickoff Pulse.

Tests run against an isolated SQLite database + a temporary library root, so they
never touch the real Postgres instance or the repo's working files.
"""

import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def lib_env(tmp_path, monkeypatch):
    """Point db + library at a throwaway SQLite DB and media root for one test.

    Returns the (db, library) modules with a fresh, initialized schema.
    """
    db_path = tmp_path / "test.db"
    lib_root = tmp_path / "library"
    monkeypatch.setenv("KICKOFF_DB_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("KICKOFF_LIBRARY_ROOT", str(lib_root))

    import db
    import library
    importlib.reload(db)
    importlib.reload(library)

    db.init_db()
    return db, library


@pytest.fixture
def sample_events():
    """A small, representative event log covering goals, shots, cards, passes."""
    return [
        {"timestamp": "2026-06-10T20:00:00+00:00", "match_time": "05:40",
         "team": "Home", "player": "#10", "action": "goal", "result": "scored",
         "location": "box", "status": "approved", "raw_text": "goal home"},
        {"timestamp": "2026-06-10T20:01:00+00:00", "match_time": "12:00",
         "team": "Home", "player": "#10", "action": "shot",
         "result": "on target", "status": "approved", "raw_text": "home shot"},
        {"timestamp": "2026-06-10T20:02:00+00:00", "match_time": "18:30",
         "team": "Away", "player": "#7", "action": "pass", "result": "complete",
         "location": "midfield", "status": "approved", "raw_text": "away pass"},
        {"timestamp": "2026-06-10T20:03:00+00:00", "match_time": "22:10",
         "team": "Away", "player": "#7", "action": "card", "result": "yellow",
         "status": "approved", "raw_text": "yellow away 7"},
        {"timestamp": "2026-06-10T20:04:00+00:00", "match_time": "30:00",
         "team": "Home", "player": None, "action": "tackle", "result": "won",
         "status": "approved", "raw_text": "home tackle"},
        # A denied event must be excluded from aggregates.
        {"timestamp": "2026-06-10T20:05:00+00:00", "match_time": "31:00",
         "team": "Home", "action": "goal", "result": "scored",
         "status": "denied", "raw_text": "disallowed"},
    ]
