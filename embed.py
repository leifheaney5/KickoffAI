#!/usr/bin/env python3
"""
Kickoff Pulse — semantic search over the match library (pgvector + Ollama).

Embeds each match (name, summary, notable events, voice notes) with a local
Ollama embedding model and stores the vector in Postgres via the pgvector
extension. The Library page can then rank matches by meaning, not just keywords.

Postgres-only: when the app is on the SQLite fallback, every function here is a
graceful no-op (is_enabled() is False) so the rest of the library keeps working.
"""

from __future__ import annotations

import os

import requests
from sqlalchemy import text

import db

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.environ.get("KICKOFF_EMBED_MODEL", "nomic-embed-text")


def is_enabled() -> bool:
    """Semantic search needs pgvector, which means a Postgres backend."""
    return db.DB_URL.startswith("postgresql")


def embed_text(s: str) -> list:
    """Embed a string via the local Ollama embeddings endpoint."""
    r = requests.post(f"{OLLAMA_URL}/api/embeddings",
                      json={"model": EMBED_MODEL, "prompt": s or ""}, timeout=60)
    r.raise_for_status()
    return r.json()["embedding"]


def _vec_literal(vec) -> str:
    """pgvector text literal: [0.1,0.2,...]."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def init_vector() -> bool:
    """Create the extension + embeddings table (dim from a probe). Idempotent.

    Returns False (and does nothing) when not on Postgres or when Ollama/the
    embedding model isn't reachable, so callers can degrade gracefully.
    """
    if not is_enabled():
        return False
    try:
        dim = len(embed_text("probe"))
    except Exception:
        return False
    with db.get_engine().begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS match_embeddings ("
            "match_id uuid PRIMARY KEY REFERENCES matches(id) ON DELETE CASCADE,"
            "content text,"
            f"embedding vector({dim}))"))
    return True


def build_content(name: str, summary: str, events: list, notes: list) -> str:
    """A compact text blob that captures what a match was 'about'."""
    parts = [name or "", summary or ""]
    # Notable events (goals, cards, shots) read like a story of the match.
    notable = [e for e in events
               if (e.get("action") in {"goal", "card", "shot", "save"}
                   or (e.get("result") or "") == "scored")]
    for e in notable[:60]:
        seg = " ".join(str(x) for x in (
            e.get("match_time"), e.get("team"), e.get("player"),
            e.get("action"), e.get("result"), e.get("location")) if x)
        if seg:
            parts.append(seg)
    for n in notes:
        if n.get("text"):
            parts.append(n["text"])
    return "\n".join(p for p in parts if p)[:8000]


def index_match(match_id, content: str) -> bool:
    """Upsert a match's embedding. No-op when disabled."""
    if not is_enabled():
        return False
    try:
        vec = _vec_literal(embed_text(content))
    except Exception:
        return False
    with db.get_engine().begin() as conn:
        conn.execute(text(
            "INSERT INTO match_embeddings (match_id, content, embedding) "
            "VALUES (:mid, :c, (:v)::vector) "
            "ON CONFLICT (match_id) DO UPDATE SET content = :c, "
            "embedding = (:v)::vector"),
            {"mid": str(match_id), "c": content[:8000], "v": vec})
    return True


def search(query: str, k: int = 20):
    """Rank matches by cosine similarity to `query`.

    Returns a list of (match_id_str, score in 0..1) best-first, or None when
    semantic search is unavailable (SQLite, no table yet, or Ollama down).
    """
    if not is_enabled():
        return None
    try:
        qv = _vec_literal(embed_text(query))
    except Exception:
        return None
    try:
        with db.get_engine().begin() as conn:
            rows = conn.execute(text(
                "SELECT match_id, 1 - (embedding <=> (:v)::vector) AS score "
                "FROM match_embeddings "
                "ORDER BY embedding <=> (:v)::vector LIMIT :k"),
                {"v": qv, "k": k}).all()
    except Exception:
        return None
    return [(str(r[0]), float(r[1])) for r in rows]


if __name__ == "__main__":
    print("pgvector enabled:", is_enabled())
    print("init_vector:", init_vector())
