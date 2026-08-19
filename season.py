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


def possession_trend(matches: list, team: str = None) -> list:
    """Camera-measured possession per match, oldest first.

    Only **measured** runs are included. A run the trust gate graded indicative
    is real signal for a single match — the report shows it, labelled — but
    averaging it into a season trend silently corrupts the trend, because the
    error is not random: a run that rarely saw the ball misattributes possession
    rather than merely adding noise.

    `matches`: dicts with played_on, home_team, away_team, vision_verdict,
    vision_home_possession, vision_away_possession. Pass `team` to get that
    side's own share regardless of whether it played home or away.
    Returns [{played_on, opponent, possession, home}].
    """
    rows = []
    for m in matches:
        if (m.get("vision_verdict") or "") != "measured":
            continue
        home = (m.get("home_team") or "").strip()
        away = (m.get("away_team") or "").strip()
        hp = float(m.get("vision_home_possession") or 0.0)
        ap = float(m.get("vision_away_possession") or 0.0)
        if not (hp or ap):
            continue
        if team is None:
            rows.append({"played_on": m.get("played_on"), "home_team": home,
                         "away_team": away, "home_possession": round(hp, 1),
                         "away_possession": round(ap, 1)})
        elif team == home:
            rows.append({"played_on": m.get("played_on"), "opponent": away,
                         "possession": round(hp, 1), "home": True})
        elif team == away:
            rows.append({"played_on": m.get("played_on"), "opponent": home,
                         "possession": round(ap, 1), "home": False})
    rows.sort(key=lambda r: (r.get("played_on") is None, r.get("played_on")))
    return rows


def vision_coverage(matches: list) -> dict:
    """How much of the season the camera actually covered, and how well.

    Season figures are only as good as the runs behind them, so this is the
    honest denominator: how many matches have a measured camera run at all.
    """
    counts = Counter((m.get("vision_verdict") or "none") for m in matches)
    total = len(matches)
    measured = counts.get("measured", 0)
    return {
        "matches": total,
        "measured": measured,
        "indicative": counts.get("indicative", 0),
        "unusable": counts.get("unusable", 0),
        "none": counts.get("none", 0),
        "measured_pct": round(100 * measured / total) if total else 0,
        "mean_ball_rate": round(
            sum(float(m.get("vision_ball_rate") or 0.0) for m in matches
                if (m.get("vision_verdict") or "") == "measured")
            / measured, 3) if measured else 0.0,
    }


def top_scorers(goal_rows: list) -> list:
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
            for (p, t), n in counts.most_common()]
