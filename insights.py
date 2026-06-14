#!/usr/bin/env python3
"""
Kickoff Pulse — match insight engine.

Pure functions that turn the raw event log into analytical signals: a decaying
"momentum" series (who is pressing, and when the game swung), a few headline
numbers, and a compact textual context that the local LLM analyst reads to
answer questions. No Streamlit / network here — easy to test.
"""

import re

# Per-action momentum weight (merit credited to the acting team). Tuned so a
# goal dominates, shots/saves matter, and routine passes barely move it.
WEIGHTS = {
    "goal": 6.0, "shot": 2.0, "save": 2.0, "tackle": 1.2, "interception": 1.2,
    "clearance": 0.8, "corner": 1.0, "cross": 0.7, "dribble": 0.8, "pass": 0.3,
    "offside": -0.5, "foul": -0.8, "substitution": 0.0,
}


def event_weight(e: dict) -> float:
    action = (e.get("action") or "").lower()
    result = (e.get("result") or "").lower()
    if action == "goal" or result == "scored":
        return 6.0
    if action == "card" or action.endswith("_card"):
        return -3.0 if ("red" in result or action == "red_card") else -1.2
    w = WEIGHTS.get(action, 0.3 if action else 0.0)
    if action == "shot" and result in ("on target", "saved"):
        w += 1.0
    if action == "pass" and result == "incomplete":
        w = 0.0
    return w


def parse_minute(e: dict, fallback: float) -> float:
    """Match minute as a float from 'MM:SS' (+added). Falls back when absent."""
    mt = (e.get("match_time") or "").strip()
    m = re.match(r"(\d+):(\d+)", mt)
    if not m:
        return fallback
    minute = int(m.group(1)) + int(m.group(2)) / 60.0
    add = re.search(r"\+(\d+):(\d+)", mt)
    if add:
        minute += int(add.group(1)) + int(add.group(2)) / 60.0
    return minute


def momentum_series(events: list, decay: float = 0.82) -> list:
    """Decaying momentum over time.

    Each row: {minute, momentum, home, away}. momentum > 0 = Home pressure,
    < 0 = Away. Recent events dominate (older ones decay toward zero), so the
    curve reads like a pressure wave rather than a cumulative tally.
    """
    rows = []
    m = 0.0
    prev = 0.0
    for e in events:
        team = e.get("team")
        if team in ("Home", "Away"):
            w = event_weight(e)
            m = m * decay + (w if team == "Home" else -w)
        else:
            m *= decay
        minute = parse_minute(e, prev + 0.4)
        prev = minute
        rows.append({
            "minute": round(minute, 2),
            "momentum": round(m, 3),
            "home": round(max(m, 0.0), 3),
            "away": round(min(m, 0.0), 3),
        })
    return rows


def momentum_leader(events: list):
    """('Home'|'Away'|None, strength) from the final momentum value."""
    rows = momentum_series(events)
    if not rows:
        return None, 0.0
    m = rows[-1]["momentum"]
    if abs(m) < 0.4:
        return None, abs(m)
    return ("Home" if m > 0 else "Away"), abs(m)


def headline_metrics(events: list, home: dict, away: dict) -> dict:
    """A few glanceable numbers for the top of the Insights page."""
    leader, strength = momentum_leader(events)

    def conversion(team):
        return round(100 * team["Goals"] / team["Shots"]) if team["Shots"] else 0

    return {
        "events": len(events),
        "shots": (home["Shots"], away["Shots"]),
        "on_target": (home["On Target"], away["On Target"]),
        "conversion": (conversion(home), conversion(away)),
        "momentum_leader": leader,
        "momentum_strength": round(strength, 1),
    }


def build_context(events: list, home: dict, away: dict, clock="") -> str:
    """Compact, model-friendly snapshot of the match for the AI analyst."""
    lines = []
    if clock:
        lines.append(f"Match clock: {clock}")
    lines += [
        f"Score: Home {home['Goals']} - {away['Goals']} Away.",
        f"Shots H{home['Shots']}/A{away['Shots']} "
        f"(on target H{home['On Target']}/A{away['On Target']}).",
        f"Saves H{home['Saves']}/A{away['Saves']}, "
        f"Tackles H{home['Tackles']}/A{away['Tackles']}, "
        f"Fouls H{home['Fouls']}/A{away['Fouls']}.",
        f"Cards: Home {home['Yellow Cards']}Y/{home['Red Cards']}R, "
        f"Away {away['Yellow Cards']}Y/{away['Red Cards']}R.",
        f"Corners H{home['Corners']}/A{away['Corners']}, "
        f"Passes H{home['Passes']}/A{away['Passes']}.",
    ]
    leader, strength = momentum_leader(events)
    if leader:
        lines.append(f"Current momentum favours {leader} (strength {strength:.1f}).")
    lines.append("")
    lines.append("Event log (oldest to newest):")
    for e in events[-45:]:
        t = (e.get("match_time") or "--").strip()
        team = e.get("team") or "-"
        act = e.get("action") or "?"
        res = f" {e['result']}" if e.get("result") else ""
        pl = f" {e['player']}" if e.get("player") else ""
        loc = f" @{e['location']}" if e.get("location") else ""
        lines.append(f"  [{t}] {team}{pl}: {act}{res}{loc}".rstrip())
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "You are Kickoff Pulse, an elite, level-headed soccer (football) analyst. "
    "You are given the live data and event log of a single match between two "
    "teams, Home and Away. Answer the user's question using ONLY that data. "
    "Be concise and specific: cite the numbers and events that support your "
    "point. Stay analytical and neutral — no hype, no invented details. If the "
    "data is too thin to answer, say so briefly. 2-5 sentences unless asked for "
    "more."
)

# Preset one-tap questions for the analyst.
QUICK_PROMPTS = {
    "Tactical read": "Give a short tactical read of how this match is unfolding.",
    "Who's on top?": "Which team is on top right now, and why? Reference momentum "
                     "and the key stats.",
    "Key moments": "What have been the most important moments or turning points "
                   "so far?",
    "What to change": "For the team that is struggling, what is one concrete "
                      "adjustment they should make?",
}
