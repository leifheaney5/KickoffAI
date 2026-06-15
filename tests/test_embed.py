"""Tests for semantic search helpers (embed.py).

These cover the pure helpers and the graceful-degradation path on SQLite; the
live pgvector + Ollama path is exercised manually against Postgres.
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_vec_literal():
    import embed
    assert embed._vec_literal([0.1, 0.2, 0.3]) == "[0.100000,0.200000,0.300000]"


def test_build_content_includes_key_parts(sample_events):
    import embed
    content = embed.build_content("Hub City vs FC Fred", "Solid win.",
                                  sample_events, [{"text": "great press"}])
    assert "Hub City" in content
    assert "Solid win." in content
    assert "great press" in content
    # A goal event should appear in the blob.
    assert "goal" in content


def test_disabled_on_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("KICKOFF_DB_URL", f"sqlite:///{tmp_path}/x.db")
    import db
    import embed
    importlib.reload(db)
    importlib.reload(embed)
    assert embed.is_enabled() is False
    assert embed.search("anything") is None
    assert embed.index_match("00000000-0000-0000-0000-000000000000", "x") is False
    assert embed.init_vector() is False
