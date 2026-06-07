#!/usr/bin/env python3
"""
Kickoff Pulse — shared event iconography.

A single source of truth for how each event is categorised, coloured, and
labelled, so the interactive timeline (SVG) and the exported timeline image
(Pillow) stay visually consistent. No emojis — clean geometric glyphs only.
"""

HOME_COLOR = "#1E7BFF"   # Pulse Blue (brand)
AWAY_COLOR = "#DC2626"   # red
NEUTRAL = "#9ca3af"

# Category -> badge fill colour
KIND_COLOR = {
    "goal": "#16a34a",
    "yellow": "#eab308",
    "red": "#dc2626",
    "sub": "#4DA3FF",
    "save": "#0891b2",
    "shot": "#6366f1",
    "foul": "#f97316",
    "tackle": "#7c3aed",
    "corner": "#475569",
    "offside": "#475569",
    "pass": "#94a3b8",
    "other": "#94a3b8",
}

KIND_LABEL = {
    "goal": "Goal", "yellow": "Yellow Card", "red": "Red Card",
    "sub": "Substitution", "save": "Save", "shot": "Shot", "foul": "Foul",
    "tackle": "Tackle", "corner": "Corner", "offside": "Offside",
    "pass": "Pass", "other": "Event",
}

# White SVG glyphs drawn inside the coloured badge (24x24 viewBox).
GLYPHS = {
    "goal": "<circle cx='12' cy='12' r='6' fill='white'/>",
    "yellow": "<rect x='8.5' y='6' width='7' height='12' rx='1.5' fill='white'/>",
    "red": "<rect x='8.5' y='6' width='7' height='12' rx='1.5' fill='white'/>",
    "sub": ("<g fill='none' stroke='white' stroke-width='1.7' "
            "stroke-linecap='round' stroke-linejoin='round'>"
            "<path d='M7 9.5h8'/><path d='M13 7.5l2 2-2 2'/>"
            "<path d='M17 14.5H9'/><path d='M11 12.5l-2 2 2 2'/></g>"),
    "save": "<path d='M12 4l7 3v5c0 4-7 8-7 8s-7-4-7-8V7z' fill='white'/>",
    "shot": ("<circle cx='12' cy='12' r='6' fill='none' stroke='white' "
             "stroke-width='2'/><circle cx='12' cy='12' r='1.8' fill='white'/>"),
    "foul": ("<path d='M8 8l8 8M16 8l-8 8' stroke='white' stroke-width='2' "
             "stroke-linecap='round'/>"),
    "tackle": ("<path d='M6 15l6-6 3 3M9 16l-3 1 1-3' fill='none' stroke='white' "
               "stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/>"),
    "corner": ("<path d='M8 6v12' stroke='white' stroke-width='1.8' "
               "stroke-linecap='round'/><path d='M8 6.5l7 2.5-7 2.5z' fill='white'/>"),
    "offside": ("<path d='M8 6v12' stroke='white' stroke-width='1.8' "
                "stroke-linecap='round'/><path d='M8 6.5l7 2.5-7 2.5z' "
                "fill='none' stroke='white' stroke-width='1.4'/>"),
    "pass": ("<path d='M6 12h9M12 9l3 3-3 3' fill='none' stroke='white' "
             "stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/>"),
    "other": "<circle cx='12' cy='12' r='3' fill='white'/>",
}


def event_kind(event: dict) -> str:
    """Map a logged event to a timeline category."""
    action = (event.get("action") or "").lower()
    result = (event.get("result") or "").lower()
    if action == "goal" or result == "scored":
        return "goal"
    if action == "card" or action.endswith("_card"):
        if "red" in result or action == "red_card":
            return "red"
        if "yellow" in result or action == "yellow_card":
            return "yellow"
        return "yellow"
    if action == "substitution":
        return "sub"
    if action in KIND_COLOR:
        return action
    return "other"


def kind_color(kind: str) -> str:
    return KIND_COLOR.get(kind, KIND_COLOR["other"])


def team_color(team) -> str:
    if team == "Home":
        return HOME_COLOR
    if team == "Away":
        return AWAY_COLOR
    return NEUTRAL


def badge_html(event: dict, size: int = 36) -> str:
    """Return an HTML badge (coloured disc + team-coloured ring + glyph)."""
    kind = event_kind(event)
    glyph = GLYPHS.get(kind, GLYPHS["other"])
    inner = int(size * 0.62)
    return (
        f"<div style='width:{size}px;height:{size}px;border-radius:50%;"
        f"background:{kind_color(kind)};border:3px solid {team_color(event.get('team'))};"
        f"display:flex;align-items:center;justify-content:center;"
        f"box-shadow:0 1px 3px rgba(0,0,0,.2)'>"
        f"<svg width='{inner}' height='{inner}' viewBox='0 0 24 24'>{glyph}</svg></div>"
    )
