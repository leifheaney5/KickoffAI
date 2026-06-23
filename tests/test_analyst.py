"""Tests for the library analyst (analyst.py).

The full RAG path needs live pgvector + Ollama (exercised manually); here we
cover the graceful-unavailable path and context building.
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_answer_unavailable_on_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("KICKOFF_DB_URL", f"sqlite:///{tmp_path}/x.db")
    import db
    import embed
    import analyst
    importlib.reload(db)
    importlib.reload(embed)
    importlib.reload(analyst)
    res = analyst.answer("how did we play?")
    assert res["ok"] is False
    assert "Postgres" in res["reason"]


def test_build_match_context(lib_env, sample_events):
    db, library = lib_env
    from datetime import date
    with db.session() as s:
        m = library.create_match(s, "Eagles vs Hawks", date(2026, 6, 10),
                                 "Eagles", "Hawks", 1, 0, "Solid win.")
        for e in sample_events:
            s.add(db.Event(match_id=m.id, match_time=e.get("match_time"),
                           team=e.get("team"), player=e.get("player"),
                           action=e.get("action"), result=e.get("result"),
                           location=e.get("location")))
        s.flush()
        import analyst
        ctx = analyst.build_match_context(m)
    assert "Eagles vs Hawks" in ctx
    assert "Eagles 1-0 Hawks" in ctx
    assert "Possession" in ctx
