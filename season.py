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


# Per-player metrics tracked across a season. Deliberately the things an event
# log can state plainly — no derived ratings, which would invent precision the
# data does not have.
PLAYER_METRICS = ("Goals", "Shots", "On Target", "Saves", "Tackles",
                  "Fouls", "Yellow Cards", "Red Cards")

_ACTION_METRIC = {
    "goal": "Goals", "shot": "Shots", "save": "Saves", "tackle": "Tackles",
    "foul": "Fouls",
}


def _metrics_for(event: dict) -> list:
    """Which season metrics one event contributes to."""
    action = (event.get("action") or "").lower()
    result = (event.get("result") or "").lower()
    out = []
    if action == "goal" or result == "scored":
        out += ["Goals", "Shots", "On Target"]
    elif action == "shot":
        out.append("Shots")
        if result in ("on target", "saved"):
            out.append("On Target")
    elif action in ("card", "yellow_card", "red_card"):
        out.append("Red Cards" if ("red" in result or action == "red_card")
                   else "Yellow Cards")
    elif action in _ACTION_METRIC:
        out.append(_ACTION_METRIC[action])
    return out


def player_season(event_rows: list) -> list:
    """Per-player season totals and per-match lines, best contributors first.

    `event_rows`: dicts with player, team, action, result, and the match they
    belong to (`match`, `played_on`). Everything comes from the mirrored event
    log, which has carried a player on every row since the first release — the
    season view simply never read it.

    Returns [{player, team, appearances, totals{...}, matches[...]}].
    """
    by_player = {}
    for e in event_rows or []:
        player = (e.get("player") or "").strip()
        if not player or e.get("status") == "denied":
            continue
        rec = by_player.setdefault(player, {
            "player": player, "team": (e.get("team") or "").strip(),
            "totals": {m: 0 for m in PLAYER_METRICS}, "_matches": {}})
        match_key = e.get("match") or ""
        line = rec["_matches"].setdefault(match_key, {
            "match": match_key, "played_on": e.get("played_on"),
            **{m: 0 for m in PLAYER_METRICS}})
        for metric in _metrics_for(e):
            rec["totals"][metric] += 1
            line[metric] += 1

    out = []
    for rec in by_player.values():
        matches = sorted(rec.pop("_matches").values(),
                         key=lambda m: (m["played_on"] is None, m["played_on"]))
        out.append({**rec, "appearances": len(matches), "matches": matches})
    out.sort(key=lambda r: (r["totals"]["Goals"], r["totals"]["On Target"],
                            r["appearances"]), reverse=True)
    return out


def player_form(player_row: dict, metric: str = "Goals", window: int = 3) -> dict:
    """Recent form against a player's *own* season baseline.

    Compared to themselves, never to the squad: in a youth team the spread
    between players says more about age and position than about progress, so a
    squad ranking would be a misleading thing to show a child's parent.
    """
    matches = (player_row or {}).get("matches") or []
    if not matches:
        return {"metric": metric, "recent": 0.0, "baseline": 0.0,
                "trend": "flat", "matches": 0}
    values = [m.get(metric, 0) for m in matches]
    recent = values[-window:]
    recent_avg = sum(recent) / len(recent)
    baseline = sum(values) / len(values)
    delta = recent_avg - baseline
    trend = "up" if delta > 0.25 else "down" if delta < -0.25 else "flat"
    return {"metric": metric, "recent": round(recent_avg, 2),
            "baseline": round(baseline, 2), "trend": trend,
            "matches": len(matches)}


def squad_involvement(player_rows: list, total_matches: int) -> list:
    """Appearances per player — how evenly the squad is being used.

    Many youth leagues expect roughly equal playing time, and nothing in the app
    made uneven involvement visible.
    """
    rows = []
    for p in player_rows or []:
        apps = p.get("appearances", 0)
        rows.append({
            "player": p["player"], "team": p.get("team", ""),
            "appearances": apps,
            "share": round(100 * apps / total_matches) if total_matches else 0,
        })
    rows.sort(key=lambda r: r["appearances"])
    return rows


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
