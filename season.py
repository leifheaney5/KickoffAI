#!/usr/bin/env python3
"""
Kickoff Pulse — cross-match (season) aggregation.

Pure functions that roll the match library up into season-level views: a league
table from match results and a top-scorers list from the mirrored event log. No
DB or Streamlit here, so it's easy to test; the Season page feeds it plain dicts
loaded from Postgres.
"""

from __future__ import annotations

from collections import Counter


def team_standings(matches: list) -> list:
    """Build a league table from finished matches.

    `matches`: dicts with home_team, away_team, home_score, away_score. Matches
    missing a team name are skipped. Returns rows sorted by Pts, then goal
    difference, then goals for.
    """
    table = {}

    def row(team):
        return table.setdefault(team, {
            "team": team, "P": 0, "W": 0, "D": 0, "L": 0,
            "GF": 0, "GA": 0, "GD": 0, "Pts": 0})

    for m in matches:
        h = (m.get("home_team") or "").strip()
        a = (m.get("away_team") or "").strip()
        if not h or not a:
            continue
        hs = int(m.get("home_score") or 0)
        as_ = int(m.get("away_score") or 0)
        rh, ra = row(h), row(a)
        rh["P"] += 1
        ra["P"] += 1
        rh["GF"] += hs
        rh["GA"] += as_
        ra["GF"] += as_
        ra["GA"] += hs
        if hs > as_:
            rh["W"] += 1
            ra["L"] += 1
            rh["Pts"] += 3
        elif hs < as_:
            ra["W"] += 1
            rh["L"] += 1
            ra["Pts"] += 3
        else:
            rh["D"] += 1
            ra["D"] += 1
            rh["Pts"] += 1
            ra["Pts"] += 1

    rows = list(table.values())
    for r in rows:
        r["GD"] = r["GF"] - r["GA"]
    rows.sort(key=lambda r: (r["Pts"], r["GD"], r["GF"]), reverse=True)
    return rows


def top_scorers(goal_rows: list, limit: int = 15) -> list:
    """Tally goals per (player, team) from goal events.

    `goal_rows`: dicts with player + team (the real team name). Unnamed players
    are skipped. Returns [{player, team, goals}] best-first.
    """
    counts = Counter()
    for g in goal_rows:
        player = (g.get("player") or "").strip()
        if not player:
            continue
        counts[(player, (g.get("team") or "").strip())] += 1
    return [{"player": p, "team": t, "goals": n}
            for (p, t), n in counts.most_common(limit)]
