#!/usr/bin/env python3
"""
Kickoff Pulse — shared stat engine.

Pure functions used by both the dashboard and the report generator, so the
aggregation logic lives in exactly one place.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter

import control

DATA_FILE = os.environ.get("KICKOFF_DATA_FILE", "match_data.json")

TEAMS = ("Home", "Away")

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


def save_events(events: list, path: str = None) -> None:
    """Atomically rewrite the match data file (rename is atomic).

    Mirrors the tracker's write path so the two never leave a half-written file.
    """
    path = path or DATA_FILE
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(events, fh, indent=2)
        control.atomic_replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def delete_event(timestamp: str, path: str = None) -> bool:
    """Delete the event with the given (unique) timestamp.

    Returns True if an event was removed. Re-reads the file first so a delete
    from the dashboard/timeline keeps any events the tracker logged in the
    meantime.
    """
    if not timestamp:
        return False
    path = path or DATA_FILE
    events = load_events(path)
    remaining = [e for e in events if e.get("timestamp") != timestamp]
    if len(remaining) == len(events):
        return False
    save_events(remaining, path)
    return True


def pop_last_event(path: str = None) -> dict | None:
    """Remove and return the most recently logged event, or None if empty.

    Re-reads the file before popping so concurrent tracker writes aren't lost.
    """
    path = path or DATA_FILE
    events = load_events(path)
    if not events:
        return None
    removed = events.pop()
    save_events(events, path)
    return removed


def update_event(timestamp: str, updates: dict, path: str = None) -> bool:
    """Merge `updates` into the event with the given timestamp.

    Returns True if the event was found and written. Re-reads the file first to
    preserve any events logged since the caller last loaded.
    """
    if not timestamp:
        return False
    path = path or DATA_FILE
    events = load_events(path)
    for e in events:
        if e.get("timestamp") == timestamp:
            e.update(updates)
            save_events(events, path)
            return True
    return False


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
        "Passes": sum(1 for a in actions if a == "pass"),
        "Subs": sum(1 for a in actions if a == "substitution"),
    }


def team_stats(events: list, team: str) -> dict:
    active = [e for e in events if e.get("status") != "denied"]
    return aggregate([e for e in active if e.get("team") == team])


def player_stats(events: list) -> dict:
    """Return {player: stat_block(+team)} for every named player."""
    players = {}
    active = [e for e in events if e.get("status") != "denied"]
    named = [e for e in active if e.get("player")]
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


# Weights for the possession estimate: on-ball actions that imply a team has
# the ball. Audio tracking has no ball telemetry, so possession is approximated
# from the share of these events (passes dominate; set pieces count for less).
_POSSESSION_WEIGHTS = {
    "Passes": 1.0,
    "Shots": 1.0,
    "On Target": 0.5,
    "Corners": 0.5,
    "Goals": 1.0,
}


def possession(home: dict, away: dict) -> tuple:
    """Estimate possession percentages (home, away) as integers summing to 100.

    Derived from each side's share of on-ball actions (see _POSSESSION_WEIGHTS).
    Falls back to a 50/50 split when there is nothing to go on, so callers can
    always render a bar without guarding for empty data.
    """
    def weight(team: dict) -> float:
        return sum(team.get(k, 0) * w for k, w in _POSSESSION_WEIGHTS.items())

    h, a = weight(home), weight(away)
    total = h + a
    if total <= 0:
        return 50, 50
    hp = round(h / total * 100)
    return hp, 100 - hp


