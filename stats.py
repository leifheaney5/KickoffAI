#!/usr/bin/env python3
"""
KickoffAI — shared stat engine.

Pure functions used by both the dashboard and the report generator, so the
aggregation logic lives in exactly one place.
"""

import json
import os
from collections import Counter

DATA_FILE = os.environ.get("KICKOFF_DATA_FILE", "match_data.json")

TEAMS = ("Home", "Away")

# Results that count as a "successful" action for the possession estimate.
POSITIVE_RESULTS = {
    "complete", "scored", "on target", "saved", "won",
    "successful", "blocked",  # a block is a successful defensive action
}

# Stat rows shown for each team / player, in display order.
STAT_KEYS = [
    "Goals", "Shots", "On Target", "Saves", "Tackles", "Fouls",
    "Yellow Cards", "Red Cards", "Corners", "Offsides", "Passes",
]


def load_events(path: str = None) -> list:
    """Read the match data file, tolerant of a mid-write empty/partial file."""
    path = path or DATA_FILE
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def _res(event: dict) -> str:
    return (event.get("result") or "").lower()


def aggregate(rows: list) -> dict:
    """Compute the standard stat block for a list of events."""
    actions = [e.get("action") for e in rows]

    def card(color: str) -> int:
        return sum(
            1 for e in rows
            if (e.get("action") == "card" and color in _res(e))
            or e.get("action") == f"{color}_card"
        )

    def on_target(e: dict) -> bool:
        return e.get("action") == "shot" and _res(e) in {"on target", "scored", "saved"}

    goals = sum(1 for e in rows if e.get("action") == "goal" or _res(e) == "scored")
    passes = sum(1 for a in actions if a == "pass")
    passes_complete = sum(
        1 for e in rows if e.get("action") == "pass" and _res(e) == "complete"
    )

    return {
        "Goals": goals,
        "Shots": sum(1 for a in actions if a == "shot") + goals,
        "On Target": sum(1 for e in rows if on_target(e)) + goals,
        "Saves": sum(1 for a in actions if a == "save"),
        "Tackles": sum(1 for a in actions if a == "tackle"),
        "Fouls": sum(1 for a in actions if a == "foul"),
        "Yellow Cards": card("yellow"),
        "Red Cards": card("red"),
        "Corners": sum(1 for a in actions if a == "corner"),
        "Offsides": sum(1 for a in actions if a == "offside"),
        "Passes": passes,
        "Subs": sum(1 for a in actions if a == "substitution"),
        "Pass %": round(100 * passes_complete / passes) if passes else 0,
        "_successful": sum(
            1 for e in rows
            if _res(e) in POSITIVE_RESULTS
            or e.get("action") in {"pass", "dribble", "cross"}
        ),
    }


def team_stats(events: list, team: str) -> dict:
    return aggregate([e for e in events if e.get("team") == team])


def player_stats(events: list) -> dict:
    """Return {player: stat_block(+team)} for every named player."""
    players = {}
    named = [e for e in events if e.get("player")]
    by_player = {}
    for e in named:
        by_player.setdefault(e["player"], []).append(e)
    for player, rows in by_player.items():
        block = aggregate(rows)
        # Assign the team the player is most often associated with.
        teams = Counter(r.get("team") for r in rows if r.get("team"))
        block["Team"] = teams.most_common(1)[0][0] if teams else None
        block["Events"] = len(rows)
        players[player] = block
    return players


def possession(home: dict, away: dict):
    h, a = home["_successful"], away["_successful"]
    total = h + a
    if total == 0:
        return 50.0, 50.0
    return round(100 * h / total, 1), round(100 * a / total, 1)
