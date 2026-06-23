#!/usr/bin/env python3
"""
Kickoff Pulse — library-wide AI analyst (RAG).

Answers questions across the whole match library: retrieves the most relevant
matches via pgvector semantic search, builds a grounded context from each
(score, stats, notable events, summary), and asks the local Ollama model to
answer using only that evidence. Cites the matches it drew on.

Postgres-only (needs pgvector); returns a structured "unavailable" result on the
SQLite fallback so the UI can explain why.
"""

from __future__ import annotations

import os
import uuid

import requests

import db
import embed
import stats as S

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

SYSTEM_PROMPT = (
    "You are Kickoff Pulse's season analyst. You are given context for several "
    "matches retrieved from the user's match library. Answer the question using "
    "ONLY that context — compare across the matches when useful, cite specific "
    "scores, stats, and events, and stay neutral and concise. If the context "
    "doesn't contain the answer, say so plainly rather than guessing."
)

QUICK_PROMPTS = {
    "Season form": "How has the team been performing across these matches?",
    "Best performance": "Which match was the strongest performance, and why?",
    "Recurring issues": "What problems or patterns recur across these matches?",
    "Top contributors": "Which players stand out across these matches?",
}


def _events_as_dicts(match) -> list:
    return [{"match_time": e.match_time, "team": e.team, "player": e.player,
             "action": e.action, "result": e.result, "location": e.location,
             "status": "approved"} for e in match.events]


def build_match_context(match) -> str:
    """A compact, factual block describing one match for the model."""
    evs = _events_as_dicts(match)
    home = S.team_stats(evs, "Home")
    away = S.team_stats(evs, "Away")
    hp, ap = S.possession(home, away)
    ht = match.home_team or "Home"
    at = match.away_team or "Away"
    lines = [
        f"MATCH: {match.name}",
        f"Date: {match.played_on or '—'}   Competition: {match.competition or '—'}",
        f"Final: {ht} {match.home_score}-{match.away_score} {at}",
        f"Possession {hp}%-{ap}% | Shots {home['Shots']}-{away['Shots']} | "
        f"On target {home['On Target']}-{away['On Target']} | "
        f"Cards {home['Yellow Cards'] + home['Red Cards']}-"
        f"{away['Yellow Cards'] + away['Red Cards']}",
    ]
    if match.summary:
        lines.append(f"Summary: {match.summary}")
    notable = [e for e in evs if e["action"] in ("goal", "card")
               or e["result"] == "scored"]
    for e in notable[:15]:
        seg = " ".join(str(x) for x in (e["match_time"], e["team"], e["player"],
                                        e["action"], e["result"]) if x)
        if seg:
            lines.append(f"  - {seg}")
    return "\n".join(lines)


def answer(question: str, k: int = 5) -> dict:
    """RAG answer over the library.

    Returns {"ok": True, "answer": str, "sources": [...]} or
    {"ok": False, "reason": str} when unavailable.
    """
    if not embed.is_enabled():
        return {"ok": False,
                "reason": "The analyst needs the Postgres backend (pgvector). "
                          "Start it with 'docker compose up -d'."}
    hits = embed.search(question, k=k)
    if hits is None:
        return {"ok": False,
                "reason": "Couldn't run semantic search — is Ollama running and "
                          "the embedding model pulled (ollama pull nomic-embed-text)?"}
    if not hits:
        return {"ok": False,
                "reason": "No matches are indexed yet. Archive some matches first."}

    contexts, sources = [], []
    with db.session() as s:
        for mid, score in hits:
            m = s.get(db.Match, uuid.UUID(mid))
            if m is None:
                continue
            contexts.append(build_match_context(m))
            sources.append({"name": m.name, "slug": m.slug,
                            "score": round(score, 3)})

    if not contexts:
        return {"ok": False, "reason": "Retrieved matches were missing."}

    payload = {
        "model": OLLAMA_MODEL, "stream": False, "options": {"temperature": 0.3},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": f"MATCHES:\n\n{chr(10).join(contexts)}\n\n"
                        f"QUESTION: {question}"},
        ],
    }
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        ans = r.json()["message"]["content"].strip()
    except Exception as exc:
        return {"ok": False, "reason": f"Could not reach the model: {exc}"}

    return {"ok": True, "answer": ans, "sources": sources}
