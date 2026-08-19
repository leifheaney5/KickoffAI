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
    "clearance": 0.8, "corner": 1.0, "cross": 0.8, "dribble": 0.8, "pass": 0.3,
    "offside": -0.5, "foul": -1.0, "substitution": 0.0,
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


def event_source(e: dict) -> str:
    """Which ingest logged this event: "vision" (the Eye) or "audio" (the mic)."""
    return "vision" if (e.get("source") == "vision") else "audio"


def momentum_series(events: list, decay: float = 0.82,
                    vision_weight: float = 1.0) -> list:
    """Decaying momentum over time, fusing both ingests.

    Each row: {minute, momentum, home, away}. momentum > 0 = Home pressure,
    < 0 = Away. Recent events dominate (older ones decay toward zero), so the
    curve reads like a pressure wave rather than a cumulative tally.

    ``vision_weight`` scales the contribution of camera-derived events (see
    quality.momentum_weight). A run where the Eye barely saw the ball would
    otherwise produce a confident-looking curve built on noise, so a poor run
    nudges the line rather than driving it. 1.0 treats both ingests equally;
    0.0 makes the curve audio-only.
    """
    rows = []
    m = 0.0
    prev = 0.0
    for e in events:
        team = e.get("team")
        if team in ("Home", "Away"):
            w = event_weight(e)
            if event_source(e) == "vision":
                w *= vision_weight
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


def momentum_leader(events: list, vision_weight: float = 1.0):
    """('Home'|'Away'|None, strength) from the final momentum value."""
    rows = momentum_series(events, vision_weight=vision_weight)
    if not rows:
        return None, 0.0
    m = rows[-1]["momentum"]
    if abs(m) < 0.4:
        return None, abs(m)
    return ("Home" if m > 0 else "Away"), abs(m)


def vision_pressure(events: list, window: float = 3.0, min_passes: int = 6) -> list:
    """Passages where the camera saw one side stringing passes together.

    A burst of vision-detected passes by a single team inside a short window is
    the Eye's own read on who is controlling the ball — independent of anything
    the mic heard. Returns [{minute, team, passes}] for the densest passages.

    This is deliberately built from bridged pass events rather than by re-parsing
    the multi-megabyte tracking document: the passes already carry a minute and a
    team, and the report should not need the frame data to say something useful.
    """
    vpasses = [e for e in events
               if event_source(e) == "vision"
               and (e.get("action") or "").lower() == "pass"
               and e.get("team") in ("Home", "Away")
               and e.get("status") != "denied"]
    if not vpasses:
        return []

    timed = sorted(((parse_minute(e, 0.0), e["team"]) for e in vpasses),
                   key=lambda p: p[0])
    passages, i = [], 0
    while i < len(timed):
        start, team = timed[i]
        j, count = i, 0
        while j < len(timed) and timed[j][0] - start <= window:
            if timed[j][1] == team:
                count += 1
            j += 1
        if count >= min_passes:
            passages.append({"minute": round(start, 2), "team": team,
                             "passes": count})
            i = j                      # don't re-report the same passage
        else:
            i += 1
    return passages


def key_moments(events: list, max_momentum: int = 4, vision_weight: float = 1.0,
                max_vision: int = 4) -> list:
    """Auto-tag the match's notable moments for the report.

    Fuses three signals so a coach sees the turning points at a glance:

      * discrete play-by-play events (goals, cards, shots on target)
      * momentum peaks (sustained pressure, blending everything logged)
      * camera-seen passing passages (what the Eye watched, independent of audio)

    Returns dicts sorted by match minute::

        {minute, mmss, team, type, label, source, confirmed}

    ``source`` is "audio", "momentum" or "vision". ``confirmed`` is True when a
    *different* ingest independently flagged the same team around the same
    minute — the one thing neither stream can establish alone, and the strongest
    signal in the list.
    """
    moments = []

    def mmss(minute: float) -> str:
        return f"{int(minute):02d}:{int(round((minute % 1) * 60)):02d}"

    for e in events:
        if e.get("status") == "denied":
            continue
        action = (e.get("action") or "").lower()
        result = (e.get("result") or "").lower()
        team = e.get("team")
        who = e.get("player")
        minute = parse_minute(e, 0.0)
        suffix = f" ({who})" if who else ""
        if action == "goal" or result == "scored":
            moments.append((minute, team, "goal", f"GOAL - {team}{suffix}"))
        elif action == "red_card" or (action == "card" and "red" in result):
            moments.append((minute, team, "red_card", f"Red card - {team}{suffix}"))
        elif action == "yellow_card" or (action == "card" and "yellow" in result):
            moments.append((minute, team, "yellow_card",
                            f"Yellow card - {team}{suffix}"))
        elif action == "shot" and result in ("on target", "saved"):
            moments.append((minute, team, "shot_on_target",
                            f"Shot on target - {team}{suffix}"))

    discrete = [
        {"minute": m, "mmss": mmss(m), "team": t, "type": k, "label": lab,
         "source": "audio"}
        for (m, t, k, lab) in moments
    ]

    # Sustained-pressure peaks: local maxima of |momentum| above a threshold,
    # spaced apart so we surface distinct passages rather than one long run.
    rows = momentum_series(events, vision_weight=vision_weight)
    peaks = []
    THRESH, SPACING = 2.5, 4.0  # strength units, minutes apart
    for i in range(1, len(rows) - 1):
        mag = abs(rows[i]["momentum"])
        if mag < THRESH:
            continue
        if mag < abs(rows[i - 1]["momentum"]) or mag <= abs(rows[i + 1]["momentum"]):
            continue
        minute = rows[i]["minute"]
        if any(abs(minute - p["minute"]) < SPACING for p in peaks):
            continue
        team = "Home" if rows[i]["momentum"] > 0 else "Away"
        peaks.append({"minute": minute, "mmss": mmss(minute), "team": team,
                      "type": "momentum_swing",
                      "label": f"Sustained {team} pressure", "source": "momentum"})
    peaks.sort(key=lambda p: abs(p["minute"]))
    peaks = sorted(peaks, key=lambda p: p["minute"])[:max_momentum]

    # What the camera saw, on its own terms. Skipped when the run was too poor
    # to contribute (vision_weight 0), so an unusable run adds no noise.
    seen = []
    if vision_weight > 0:
        for p in vision_pressure(events)[:max_vision]:
            seen.append({
                "minute": p["minute"], "mmss": mmss(p["minute"]),
                "team": p["team"], "type": "vision_pressure",
                "label": f"Camera: {p['team']} keeping the ball "
                         f"({p['passes']} passes)",
                "source": "vision"})

    out = sorted(discrete + peaks + seen, key=lambda m: m["minute"])

    # Cross-source confirmation: mark moments that a *different* ingest also
    # flagged for the same team nearby. Agreement between an ear and an eye is
    # far stronger evidence than either alone, so it is worth surfacing.
    CONFIRM_WINDOW = 3.0
    for m in out:
        m["confirmed"] = any(
            o is not m
            and o["team"] == m["team"]
            and o["source"] != m["source"]
            and abs(o["minute"] - m["minute"]) <= CONFIRM_WINDOW
            for o in out)
    return out


def headline_metrics(events: list, home: dict, away: dict,
                     vision_weight: float = 1.0) -> dict:
    """A few glanceable numbers for the top of the Insights page."""
    leader, strength = momentum_leader(events, vision_weight=vision_weight)

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
    "You are Kickoff Pulse AI, an elite, level-headed soccer (football) analyst. "
    "You are given the live data and event log of a single match between two "
    "teams, Home and Away. Answer the user's question using ONLY that data. "
    "Do NOT generate answers that arem't derived directly from the data/context provided."
    "Be concise and specific: cite the numbers and events that support your "
    "point. Stay analytical and neutral — no hype, no invented details. If the "
    "data is too thin to answer, say so briefly. 2-5 sentences unless asked for "
    "more/a deeper analytical response."
)

# Preset one-tap questions for the analyst.
QUICK_PROMPTS = {
    "Tactical read": "Give a short tactical read of how this match is unfolding.",
    "Who's on top?": "Which team is on top right now, and why? Reference momentum "
                     "and the key stats.",
    "Key moments": "What have been the most important moments or turning points "
                   "so far?",
    "What to change?": "For the team that is struggling, what is one concrete "
                      "adjustment they should make, and why?",
    "Who to sub?": "For the team that is struggling, what is one justifiable substitution "
                      "they should make, and why?"
}
