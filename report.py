#!/usr/bin/env python3
"""
Kickoff Pulse — report generator.

Compiles the logged match data into:
  - an email-friendly plain-text report (reports/match_report_<ts>.txt)
  - a clean PDF report                  (reports/match_report_<ts>.pdf)
  - a structured JSON report payload    (reports/match_report_<ts>_payload.json)
and archives a copy of the raw data     (reports/match_data_<ts>.json)

Usable from the command line:
    python report.py
or programmatically from the dashboard:
    import report; paths = report.generate(summary="...", clock="73:12")
"""

import csv
import io
import json
import os
import re
import shutil
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape, quoteattr

import control
import insights as IN
import stats as S
import timeline_image as TL

REPORTS_DIR = os.environ.get("KICKOFF_REPORTS_DIR", "exports")

# The Eye's output. Read alongside the audio event log so the report can show
# both what was heard and what was seen, each labelled with its own provenance.
VISION_STATS_FILE = os.environ.get("KICKOFF_VISION_STATS_FILE",
                                   "match_stats.json")

HOME_RGB = (30, 123, 255)   # Pulse Blue (brand)
AWAY_RGB = (220, 38, 38)    # red
NAVY_RGB = (7, 26, 61)      # Primary Navy (brand)
INK = (17, 24, 39)          # Dark Text (brand)
MUTED = (107, 114, 128)
LINE = (222, 226, 230)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _event_time(e: dict) -> str:
    """Prefer the match clock if it was stamped, else the wall time."""
    if e.get("match_time"):
        return str(e["match_time"])
    ts = e.get("timestamp", "")
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M:%S")
    except ValueError:
        return ts


def _event_summary(e: dict) -> str:
    when = _event_time(e)
    action = e.get("action")
    result = e.get("result")
    raw_text = e.get("raw_text")
    parts = [
        f"[{when}]" if when else None,
        e.get("team"),
        f"{action} ({result})" if action and result else action or result,
        f"by {e['player']}" if e.get("player") else None,
        f"@ {e['location']}" if e.get("location") else None,
        (f"status: {e['status']}" if e.get("status") != "approved"
         and e.get("status") else None),
        f'"{raw_text}"' if raw_text and not action else None,
    ]
    return " / ".join(str(p) for p in parts if p) or f'"{raw_text or ""}"'


# Compact subset of stats worth splitting per half (keeps the table readable).
HALF_STAT_KEYS = [
    "Goals", "Shots", "On Target", "Corners", "Fouls", "Passes",
    "Possession %",
]

DERIVED_STAT_KEYS = [
    "Shot Accuracy %",
    "Shot Conversion %",
    "Shots Off Target",
    "Defensive Actions",
    "Total Cards",
]


def load_vision(stats_path: str = None) -> dict:
    """Load the vision document + its trust verdict, or {} when there is none.

    Returns {"possession": (home, away), "passes": n, "quality": {...}} so the
    report can present vision figures beside the audio ones without either
    silently overriding the other.
    """
    import quality as Q

    stats_path = stats_path or VISION_STATS_FILE
    if not os.path.exists(stats_path):
        return {}
    try:
        with open(stats_path, "r", encoding="utf-8") as fh:
            stats = json.load(fh)
    except (ValueError, OSError):
        return {}
    if not isinstance(stats, dict):
        return {}

    ev = stats.get("statistical_events", {}) or {}
    poss = ev.get("possession_summary", {}) or {}
    assessment = Q.assess_stats(stats)
    if not Q.is_usable(assessment):
        # Still return the assessment: the report should say the Eye ran and
        # produced nothing usable, rather than staying silent about it.
        return {"quality": assessment, "usable": False}
    return {
        "possession": (float(poss.get("team_home_percentage", 0.0)),
                       float(poss.get("team_away_percentage", 0.0))),
        "passes": len(ev.get("passing_stats", []) or []),
        "quality": assessment,
        "usable": True,
    }


def _vision_weight(vision) -> float:
    """How heavily camera events should count toward momentum for this match."""
    import quality as Q

    return Q.momentum_weight((vision or {}).get("quality"))


def _half_stat_pair(home_half: dict, away_half: dict, key: str) -> tuple:
    if key == "Possession %":
        hp, ap = S.possession(home_half, away_half)
        return f"{hp}%", f"{ap}%"
    return home_half.get(key, 0), away_half.get(key, 0)


def _collect(events):
    home = S.team_stats(events, "Home")
    away = S.team_stats(events, "Away")
    return {
        "home": home,
        "away": away,
        "home_halves": S.team_stats_by_half(events, "Home"),
        "away_halves": S.team_stats_by_half(events, "Away"),
        "players": S.player_stats(events),
        "subs": [e for e in events if e.get("action") == "substitution"],
    }


def _percentage(numerator: int, denominator: int) -> int:
    return round(100 * numerator / denominator) if denominator else 0


def _conversion(team: dict) -> int:
    """Goals-per-shot as a percentage (0 when no shots were taken)."""
    return _percentage(team.get("Goals", 0), team.get("Shots", 0))


def _derived_stats(block: dict) -> dict:
    shots = block.get("Shots", 0)
    on_target = block.get("On Target", 0)
    return {
        "Shot Accuracy %": _percentage(on_target, shots),
        "Shot Conversion %": _conversion(block),
        "Shots Off Target": max(shots - on_target, 0),
        "Defensive Actions": block.get("Saves", 0) + block.get("Tackles", 0),
        "Total Cards": block.get("Yellow Cards", 0) + block.get("Red Cards", 0),
    }


def scoring_summary(events) -> list:
    """Goals in match order: [{time, team, player}] (denied goals excluded)."""
    out = []
    for e in events:
        if e.get("status") == "denied":
            continue
        if e.get("action") == "goal" or (e.get("result") or "").lower() == "scored":
            out.append({
                "time": _event_time(e),
                "team": e.get("team") or "-",
                "player": e.get("player") or "",
            })
    return out


def _potm_score(p: dict) -> float:
    """Heuristic standout-performer score from a player's stat block."""
    defensive_score = (
        p.get("Tackles", 0) * 1.6
        + p.get("Interceptions", 0) * 1.4
        + p.get("Blocks", 0) * 1.3
        + p.get("Clearances", 0) * 1.1
        + p.get("Recoveries", 0) * 0.7
    )
    return (
        p.get("Goals", 0) * 3.0
        + p.get("On Target", 0) * 1.5
        + p.get("Shots", 0) * 0.5
        + p.get("Saves", 0) * 0.9
        + defensive_score
        - p.get("Fouls", 0) * 0.4
        - p.get("Yellow Cards", 0) * 1.0
        - p.get("Red Cards", 0) * 3.0
    )


def player_of_match(players: dict):
    """Auto-pick the standout player as (name, stat_block, score), or None.

    Returns None when there are no players or no one has a positive score
    (e.g. only passes logged), so callers can simply skip the section.
    """
    if not players:
        return None
    name, p = max(players.items(),
                  key=lambda kv: (_potm_score(kv[1]), kv[1].get("Events", 0)))
    score = _potm_score(p)
    if score <= 0:
        return None
    return name, p, round(score, 1)


def _count_phrase(n: int, singular: str, plural: str = None) -> str:
    return f"{n} {singular if n == 1 else plural or singular + 's'}"


def _post_match_summary_lines(events, data, summary) -> list:
    """Blend coach notes with a concise automatic match story."""
    summary = str(summary or "").strip()

    home, away = data["home"], data["away"]
    hg, ag = home.get("Goals", 0), away.get("Goals", 0)
    if hg > ag:
        result = f"Result: Home won {hg}-{ag}."
    elif ag > hg:
        result = f"Result: Away won {ag}-{hg}."
    else:
        result = f"Result: Match finished level at {hg}-{ag}."

    hp, ap = S.possession(home, away)
    lines = [
        result,
        (f"Control: Possession Home {hp}%-{ap}% Away; shots "
         f"{home.get('Shots', 0)}-{away.get('Shots', 0)}, on target "
         f"{home.get('On Target', 0)}-{away.get('On Target', 0)}."),
    ]

    goals = scoring_summary(events)
    if goals:
        shown = []
        for g in goals[:5]:
            who = f" ({g['player']})" if g.get("player") else ""
            when = f"{g['time']} " if g.get("time") else ""
            shown.append(f"{when}{g['team']}{who}")
        more = (
            f"; +{len(goals) - len(shown)} more"
            if len(goals) > len(shown) else ""
        )
        lines.append(f"Scoring: {'; '.join(shown)}{more}.")
    else:
        lines.append("Scoring: No goals recorded.")

    leader, _strength = IN.momentum_leader(events)
    lines.append(
        f"Momentum: {leader} finished with the late pressure."
        if leader else
        "Momentum: Final pressure was balanced."
    )

    potm = player_of_match(data.get("players", {}))
    if potm:
        name, block, _score = potm
        bits = []
        for key, singular, plural in (
            ("Goals", "goal", None),
            ("On Target", "shot on target", "shots on target"),
            ("Saves", "save", None),
            ("Tackles", "tackle", None),
        ):
            value = block.get(key, 0)
            if value:
                bits.append(_count_phrase(value, singular, plural))
        if not bits and block.get("Events"):
            bits.append(_count_phrase(block["Events"], "logged event"))
        team = f" ({block.get('Team')})" if block.get("Team") else ""
        detail = ", ".join(bits) if bits else "top overall impact"
        lines.append(f"Standout: {name}{team} - {detail}.")

    if summary:
        notes = [line.strip() for line in summary.splitlines() if line.strip()]
        if notes:
            lines.append("Coach notes:")
            lines.extend(f"- {line}" for line in notes)

    return lines


_NOTE_GROUP_KEYS = (
    ("audio", "audio"),
    ("audio_notes", "audio"),
    ("voice", "audio"),
    ("voice_notes", "audio"),
    ("recorded", "audio"),
    ("recorded_notes", "audio"),
    ("written", "written"),
    ("written_notes", "written"),
    ("manual", "written"),
    ("manual_notes", "written"),
    ("typed", "written"),
    ("typed_notes", "written"),
)

_SINGLE_NOTE_KEYS = {"text", "note", "content", "body", "match_time",
                     "timestamp"}


def _note_value(note: dict, keys) -> str:
    for key in keys:
        value = note.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _note_source(note: dict, default_source: str = None) -> str:
    for key in ("source", "kind", "type", "mode"):
        value = str(note.get(key) or "").lower()
        if any(x in value for x in ("written", "manual", "typed", "text")):
            return "written"
        if any(x in value for x in ("audio", "voice", "spoken", "record")):
            return "audio"
    if default_source:
        return default_source
    return "audio" if note.get("audio") else "written"


def _normalize_note(note, default_source: str = None):
    if isinstance(note, dict):
        raw = note
    else:
        raw = {"text": note}

    text = _note_value(raw, ("text", "note", "content", "body")).strip()
    if not text:
        return None

    return {
        "match_time": _note_value(raw, ("match_time", "clock", "time")),
        "text": text,
        "source": _note_source(raw, default_source),
    }


def _collect_notes(value, groups: dict, default_source: str) -> None:
    if not value:
        return
    if isinstance(value, dict):
        if any(key in value for key in _SINGLE_NOTE_KEYS):
            note = _normalize_note(value, default_source)
            if note:
                groups[note["source"]].append(note)
            return
        for key, source in _NOTE_GROUP_KEYS:
            _collect_notes(value.get(key), groups, source)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_notes(item, groups, default_source)
        return

    note = _normalize_note(value, default_source)
    if note:
        groups[note["source"]].append(note)


def _note_groups(notes=None, written_notes=None) -> dict:
    groups = {"audio": [], "written": []}
    _collect_notes(notes, groups, "audio")
    _collect_notes(written_notes, groups, "written")
    return groups


# --------------------------------------------------------------------------- #
# CSV exports (spreadsheet-friendly: open in Excel / Sheets for analysis)
# --------------------------------------------------------------------------- #
EVENT_CSV_PREFERRED_FIELDS = ["match_time", "timestamp", "team", "player",
                              "action", "result", "location", "status",
                              "raw_text"]


def _event_csv_fields(events) -> list:
    fields = list(EVENT_CSV_PREFERRED_FIELDS)
    seen = set(fields)
    for e in events:
        for k in e:
            if k not in seen:
                seen.add(k)
                fields.append(k)
    return fields


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def build_events_csv(events) -> str:
    """The full event log as CSV — one row per event."""
    fields = _event_csv_fields(events)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(fields)
    for e in events:
        writer.writerow([_csv_value(e.get(k)) for k in fields])
    return buf.getvalue()


def _team_stats_rows(data) -> list:
    home, away = data["home"], data["away"]
    hp, ap = S.possession(home, away)
    home_extra, away_extra = _derived_stats(home), _derived_stats(away)
    rows = [["Stat", "Home", "Away"], ["Possession %", hp, ap]]
    rows.extend([k, home_extra[k], away_extra[k]] for k in DERIVED_STAT_KEYS)
    rows.extend([k, home.get(k, 0), away.get(k, 0)] for k in S.STAT_KEYS)
    seen = {"Possession %", *DERIVED_STAT_KEYS, *S.STAT_KEYS}
    for block in (home, away):
        for k in block:
            if k not in seen:
                seen.add(k)
                rows.append([k, home.get(k, 0), away.get(k, 0)])
    return rows


def _player_stats_rows(data) -> list:
    players = data["players"]
    cols = ["Player", "Team", "Events"] + S.STAT_KEYS + DERIVED_STAT_KEYS
    ordered = sorted(players.items(),
                     key=lambda kv: (kv[1]["Goals"], kv[1]["Events"]),
                     reverse=True)
    rows = [cols]
    for name, p in ordered:
        extra = _derived_stats(p)
        rows.append([name, p.get("Team") or "", p.get("Events", 0)]
                    + [p.get(k, 0) for k in S.STAT_KEYS]
                    + [extra[k] for k in DERIVED_STAT_KEYS])
    return rows


def build_team_stats_csv(data) -> str:
    """Head-to-head team stats as CSV (Stat, Home, Away)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(_team_stats_rows(data))
    return buf.getvalue()


def build_player_stats_csv(data) -> str:
    """Per-player stats as CSV, ordered by goals then activity."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(_player_stats_rows(data))
    return buf.getvalue()


def _xlsx_col(n: int) -> str:
    letters = []
    while n:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


def _xlsx_sheet(rows) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main"><sheetData>',
    ]
    for r_idx, row in enumerate(rows, 1):
        cells = []
        for c_idx, value in enumerate(row, 1):
            if value is None or value == "":
                continue
            ref = f"{_xlsx_col(c_idx)}{r_idx}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(
                    f'<c r="{ref}" t="inlineStr"><is><t>'
                    f'{escape(str(value))}</t></is></c>')
        out.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    out.append("</sheetData></worksheet>")
    return "".join(out)


def build_stats_xlsx(data, path) -> None:
    """Write team and player stats to separate workbook tabs."""
    sheets = [
        ("Team Stats", _team_stats_rows(data)),
        ("Player Stats", _player_stats_rows(data)),
    ]
    workbook_sheets = "".join(
        f'<sheet name={quoteattr(name)} sheetId="{idx}" r:id="rId{idx}"/>'
        for idx, (name, _rows) in enumerate(sheets, 1)
    )
    overrides = "".join(
        '<Override PartName="/xl/worksheets/sheet{idx}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.worksheet+xml"/>'.format(idx=idx)
        for idx in range(1, len(sheets) + 1)
    )
    rels = "".join(
        '<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet{idx}.xml"/>'.format(idx=idx)
        for idx in range(1, len(sheets) + 1)
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/'
                   '2006/content-types"><Default Extension="rels" '
                   'ContentType="application/vnd.openxmlformats-package.'
                   'relationships+xml"/><Default Extension="xml" '
                   'ContentType="application/xml"/><Override '
                   'PartName="/xl/workbook.xml" ContentType="application/vnd.'
                   'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   f'{overrides}</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships"><Relationship Id="rId1" '
                   'Type="http://schemas.openxmlformats.org/officeDocument/'
                   '2006/relationships/officeDocument" '
                   'Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/'
                   'spreadsheetml/2006/main" xmlns:r="http://schemas.'
                   'openxmlformats.org/officeDocument/2006/relationships">'
                   f'<sheets>{workbook_sheets}</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/'
                   f'package/2006/relationships">{rels}</Relationships>')
        for idx, (_name, rows) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{idx}.xml", _xlsx_sheet(rows))


def _dict_rows(rows) -> list:
    if not rows:
        return []
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]


def build_json_payload(events, data, summary, clock, match_name="",
                       lineups=None, notes=None, written_notes=None) -> dict:
    """Typed report blocks suitable for storing/indexing in the library DB."""
    home, away = data["home"], data["away"]
    hp, ap = S.possession(home, away)
    home_extra, away_extra = _derived_stats(home), _derived_stats(away)
    leader, strength = IN.momentum_leader(events)
    note_groups = _note_groups(notes, written_notes)
    generated_at = datetime.now().isoformat(timespec="seconds")

    blocks = [
        {
            "id": "metadata",
            "type": "metadata",
            "title": "Metadata",
            "payload": {
                "match_name": match_name or "Match",
                "match_date": _match_date(events),
                "generated_at": generated_at,
                "clock": clock,
                "event_count": len(events),
                "contact": "leif@leifheaney.com",
            },
        },
        {
            "id": "score",
            "type": "score",
            "title": "Final Score",
            "payload": {
                "home": home.get("Goals", 0),
                "away": away.get("Goals", 0),
            },
        },
        {
            "id": "team_stats",
            "type": "table",
            "title": "Team Stats",
            "payload": {"rows": _dict_rows(_team_stats_rows(data))},
        },
        {
            "id": "half_stats",
            "type": "table",
            "title": "By Half",
            "payload": {
                "rows": [
                    {
                        "Stat": key,
                        "1st Home": first_home,
                        "1st Away": first_away,
                        "2nd Home": second_home,
                        "2nd Away": second_away,
                    }
                    for key in HALF_STAT_KEYS
                    for first_home, first_away in [
                        _half_stat_pair(data["home_halves"]["1st"],
                                        data["away_halves"]["1st"], key)
                    ]
                    for second_home, second_away in [
                        _half_stat_pair(data["home_halves"]["2nd"],
                                        data["away_halves"]["2nd"], key)
                    ]
                ],
            },
        },
        {
            "id": "efficiency",
            "type": "metrics",
            "title": "Efficiency & Possession",
            "payload": {
                "possession": {"home": hp, "away": ap},
                "shot_accuracy": {
                    "home": home_extra["Shot Accuracy %"],
                    "away": away_extra["Shot Accuracy %"],
                },
                "shot_conversion": {
                    "home": _conversion(home),
                    "away": _conversion(away),
                },
                "momentum": {"leader": leader, "strength": strength},
            },
        },
        {
            "id": "summary",
            "type": "text",
            "title": "Post-Match Summary",
            "payload": {
                "raw": str(summary or ""),
                "lines": _post_match_summary_lines(events, data, summary),
            },
        },
        {
            "id": "scoring_summary",
            "type": "list",
            "title": "Scoring Summary",
            "payload": {"goals": scoring_summary(events)},
        },
        {
            "id": "player_stats",
            "type": "table",
            "title": "Player Stats",
            "payload": {"rows": _dict_rows(_player_stats_rows(data))},
        },
        {
            "id": "events",
            "type": "event_log",
            "title": "Events",
            "payload": {
                "items": [
                    {**event, "time": _event_time(event),
                     "summary": _event_summary(event)}
                    for event in events
                ],
            },
        },
    ]

    if control.has_lineups(lineups):
        blocks.insert(2, {
            "id": "lineups",
            "type": "lineups",
            "title": "Starting Lineups",
            "payload": {
                team.lower(): {
                    "heading": _lineup_heading(lineups, team),
                    "players": _roster_lines(lineups, team),
                }
                for team in ("Home", "Away")
            },
        })

    potm = player_of_match(data.get("players", {}))
    if potm:
        name, stat_block, score = potm
        blocks.append({
            "id": "player_of_match",
            "type": "spotlight",
            "title": "Player Of The Match",
            "payload": {"player": name, "score": score, "stats": stat_block},
        })

    for source, title in (("audio", "Audio Notes"), ("written", "Written Notes")):
        if note_groups[source]:
            blocks.append({
                "id": f"{source}_notes",
                "type": "notes",
                "title": title,
                "payload": {"items": note_groups[source]},
            })

    return {
        "schema": "kickoff.report_payload.v1",
        "generated_at": generated_at,
        "match_name": match_name or "Match",
        "blocks": blocks,
    }


def _roster_lines(lineups, team) -> list:
    """Render a team's roster as display lines like '#6  Smith'."""
    lines = []
    for p in control.roster_for(lineups, team):
        num = str(p.get("number") or "").strip()
        name = str(p.get("name") or "").strip()
        label = (f"#{num} {name}".strip() if num else name).strip()
        if label:
            lines.append(label)
    return lines


def _lineup_heading(lineups, team) -> str:
    """'HOME (4-3-3)' when a formation is set, else 'HOME'."""
    form = control.lineup_formation(lineups, team)
    return team.upper() + (f" ({form})" if form else "")


# --------------------------------------------------------------------------- #
# Plain-text report
# --------------------------------------------------------------------------- #
def build_text(events, data, summary, clock, match_name="", lineups=None,
               notes=None, written_notes=None, vision=None) -> str:
    home, away = data["home"], data["away"]
    match_date = _match_date(events)
    L = []
    w = 56

    def rule(ch="="):
        L.append(ch * w)

    rule()
    L.append("KICKOFF PULSE  -  MATCH REPORT".center(w))
    rule()
    if match_name:
        L.append(match_name.center(w))
    L.append(match_date.center(w))
    L.append("")
    L.append(f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    L.append("Contact   : leif@leifheaney.com")
    if clock:
        L.append(f"Match clock: {clock}")
    L.append(f"Events    : {len(events)}")
    L.append("")
    L.append(f"FINAL SCORE   HOME {home['Goals']}  -  {away['Goals']} AWAY")
    L.append("")

    # Starting lineups (optional)
    if control.has_lineups(lineups):
        hl = _roster_lines(lineups, "Home")
        al = _roster_lines(lineups, "Away")
        rule("-")
        L.append("STARTING LINEUPS")
        rule("-")
        L.append(f"{_lineup_heading(lineups, 'Home'):<28}"
                 f"{_lineup_heading(lineups, 'Away'):<28}")
        for i in range(max(len(hl), len(al))):
            h = hl[i] if i < len(hl) else ""
            a = al[i] if i < len(al) else ""
            L.append(f"{h[:27]:<28}{a[:27]:<28}")
        L.append("")

    rule("-")
    L.append(f"{'HOME':>10}   {'STAT':^18}   {'AWAY':<10}")
    rule("-")
    for k, h_val, a_val in _team_stats_rows(data)[1:]:
        L.append(f"{str(h_val):>10}   {k:^18}   {str(a_val):<10}")
    L.append("")

    # Per-half breakdown (key stats only) — explicit Home/Away per half
    h1, h2 = data["home_halves"], data["away_halves"]
    rule("-")
    L.append("BY HALF")
    rule("-")
    L.append(f"{'':<12}{'1st Half':^12}{'':<3}{'2nd Half':^12}")
    L.append(f"{'':<12}{'Home':>6}{'Away':>6}{'':<3}{'Home':>6}{'Away':>6}")
    for k in HALF_STAT_KEYS:
        h_1st, a_1st = _half_stat_pair(h1["1st"], h2["1st"], k)
        h_2nd, a_2nd = _half_stat_pair(h1["2nd"], h2["2nd"], k)
        L.append(f"{k:<12}{h_1st:>6}{a_1st:>6}{'':<3}"
                 f"{h_2nd:>6}{a_2nd:>6}")
    L.append("")

    # Efficiency & possession
    hp, ap = S.possession(home, away)
    home_extra, away_extra = _derived_stats(home), _derived_stats(away)
    rule("-")
    L.append("EFFICIENCY & POSSESSION")
    rule("-")
    L.append(f"{f'{hp}%':>10}   {'Possession (est)':^18}   {f'{ap}%':<10}")
    h_acc, a_acc = (
        f"{home_extra['Shot Accuracy %']}%",
        f"{away_extra['Shot Accuracy %']}%",
    )
    L.append(f"{h_acc:>10}   {'Shot Accuracy':^18}   {a_acc:<10}")
    L.append(f"{f'{_conversion(home)}%':>10}   {'Shot Conversion':^18}   "
             f"{f'{_conversion(away)}%':<10}")

    # Camera analysis, as its own labelled series — never merged into the
    # play-by-play figures above.
    if vision:
        q = vision.get("quality") or {}
        L.append("")
        rule("-")
        L.append("CAMERA ANALYSIS (THE EYE)")
        rule("-")
        L.append(f"Reliability: {q.get('label', 'Unusable')}")
        L.append(f"  {q.get('blurb', '')}")
        if vision.get("usable"):
            vh, va = vision["possession"]
            L.append(f"{f'{vh:.0f}%':>10}   {'Possession (seen)':^18}   "
                     f"{f'{va:.0f}%':<10}")
            L.append(f"  Play-by-play possession above: Home {hp}% / Away {ap}%")
            L.append(f"  Passes detected: {vision.get('passes', 0)}")
            gap = abs(vh - hp)
            if gap >= 15:
                L.append(f"  Note: the two methods differ by {gap:.0f} points "
                         f"- worth a review, not necessarily an error.")
        L.append("  Why: " + "; ".join(q.get("reasons") or ["no detail"]) + ".")

    leader, _strength = IN.momentum_leader(events,
                                           vision_weight=_vision_weight(vision))
    if leader:
        L.append(f"  {leader} finished the stronger side.")
    L.append("")

    summary_lines = _post_match_summary_lines(events, data, summary)
    rule("-")
    L.append("POST-MATCH SUMMARY")
    rule("-")
    L.extend(summary_lines)
    L.append("")

    note_groups = _note_groups(notes, written_notes)
    for title, items in (("AUDIO NOTES", note_groups["audio"]),
                         ("WRITTEN NOTES", note_groups["written"])):
        if not items:
            continue
        rule("-")
        L.append(title)
        rule("-")
        for n in items:
            mt = n.get("match_time") or ""
            L.append(f"  [{mt:>6}]  {n.get('text', '')}")
        L.append("")

    rule()
    return "\n".join(L)


# The bundled Helvetica is latin-1 only, so map common Unicode punctuation to
# ASCII and replace anything else, rather than crashing on an em-dash / smart
# quote in a summary, competition, or player name.
_PDF_REPLACE = {
    "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", "•": "-",
    " ": " ",
}


def _pdf_safe(s) -> str:
    s = str(s)
    for k, v in _PDF_REPLACE.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


# --------------------------------------------------------------------------- #
# PDF report
# --------------------------------------------------------------------------- #
def build_pdf(events, data, summary, clock, path,
              match_name="", lineups=None, notes=None, written_notes=None,
              momentum_png=None, home_logo=None, away_logo=None, vision=None):
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    home, away = data["home"], data["away"]
    match_date = _match_date(events)
    hp, ap = S.possession(home, away)

    CONTACT = "leif@leifheaney.com"
    SHADE = (244, 246, 249)     # alternating row tint
    CARD = (248, 250, 252)      # light card fill

    class Report(FPDF):
        def footer(self):
            self.set_y(-13)
            self.set_draw_color(*LINE)
            self.line(self.l_margin, self.get_y(),
                      self.l_margin + self.epw, self.get_y())
            self.ln(1)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*MUTED)
            self.cell(self.epw / 2, 6,
                      _pdf_safe(f"Kickoff Pulse  -  {CONTACT}"), align="L")
            self.cell(self.epw / 2, 6, f"Page {self.page_no()}", align="R")

    pdf = Report(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    epw = pdf.epw  # effective page width
    lm = pdf.l_margin

    def text(txt, size=11, style="", color=INK, h=6, align="L"):
        pdf.set_font("Helvetica", style, size)
        pdf.set_text_color(*color)
        pdf.cell(0, h, _pdf_safe(txt), new_x=XPos.LMARGIN, new_y=YPos.NEXT,
                 align=align)

    def section(title):
        """Section heading: a navy accent bar + uppercase title."""
        pdf.ln(1)
        y = pdf.get_y()
        pdf.set_fill_color(*NAVY_RGB)
        pdf.rect(lm, y + 0.8, 1.6, 5.2, style="F")
        pdf.set_xy(lm + 4, y)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*NAVY_RGB)
        pdf.cell(0, 7, _pdf_safe(title.upper()),
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.2)

    def frame(y0):
        """Draw a light border around content rendered from y0 to the cursor
        (only when it stayed on one page)."""
        y1 = pdf.get_y()
        if y1 > y0:
            pdf.set_draw_color(*LINE)
            pdf.rect(lm, y0, epw, y1 - y0)

    # ---- Header ----------------------------------------------------------- #
    import brand
    top = pdf.get_y()
    logo = brand.logo_pil_white()
    logo_h = 0.0
    if logo is not None:
        try:
            lw = 38
            pdf.image(logo, x=lm, y=top, w=lw)
            logo_h = lw * logo.height / logo.width
        except Exception:
            logo = None
    pdf.set_xy(lm, top + 1)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*NAVY_RGB)
    pdf.cell(0, 8, "POST-MATCH REPORT", align="R",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(lm)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, _pdf_safe(match_name or "Match"), align="R",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, _pdf_safe(match_date), align="R",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_y(max(pdf.get_y(), top + logo_h) + 1)
    meta = f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}   |   {CONTACT}"
    if clock:
        meta += f"   |   Match clock {clock}"
    meta += f"   |   {len(events)} events"
    text(meta, 9, "", MUTED, h=5)
    y = pdf.get_y()
    pdf.set_draw_color(*NAVY_RGB)
    pdf.set_line_width(0.5)
    pdf.line(lm, y, lm + epw, y)
    pdf.set_line_width(0.2)
    pdf.ln(4)

    # ---- Scoreline band (team crests flanking the score) ------------------ #
    pdf.set_fill_color(*CARD)
    pdf.set_draw_color(*LINE)
    y0 = pdf.get_y()
    band = 34
    pdf.rect(lm, y0, epw, band, style="DF")

    def _place_logo(p, x_center, box=24):
        """Center a crest (preserving aspect) within `box` mm at x_center."""
        try:
            from PIL import Image
            with Image.open(p) as im:
                iw, ih = im.size
            w, h = (box, box * ih / iw) if iw >= ih else (box * iw / ih, box)
            pdf.image(p, x=x_center - w / 2, y=y0 + (band - h) / 2, w=w, h=h)
            return True
        except Exception:
            return False

    logo_box, pad = 24, 6
    have_home = bool(home_logo and os.path.exists(home_logo)) and \
        _place_logo(home_logo, lm + pad + logo_box / 2)
    have_away = bool(away_logo and os.path.exists(away_logo)) and \
        _place_logo(away_logo, lm + epw - pad - logo_box / 2)

    inner_l = lm + (pad + logo_box if have_home else 0)
    inner_r = lm + epw - (pad + logo_box if have_away else 0)
    inner_w = inner_r - inner_l
    pdf.line(inner_l + inner_w / 2, y0 + 5, inner_l + inner_w / 2, y0 + band - 5)
    pdf.set_xy(inner_l, y0 + 6)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*HOME_RGB)
    pdf.cell(inner_w / 2, 6, "HOME", align="C")
    pdf.set_text_color(*AWAY_RGB)
    pdf.cell(inner_w / 2, 6, "AWAY", new_x=XPos.LMARGIN, new_y=YPos.NEXT,
             align="C")
    pdf.set_xy(inner_l, y0 + 15)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(*HOME_RGB)
    pdf.cell(inner_w / 2, 13, str(home["Goals"]), align="C")
    pdf.set_text_color(*AWAY_RGB)
    pdf.cell(inner_w / 2, 13, str(away["Goals"]),
             new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_y(y0 + band + 4)

    scorers = scoring_summary(events)
    potm = player_of_match(data.get("players", {}))
    if scorers or potm:
        section("Match Snapshot")
        y0 = pdf.get_y()
        gap = 4
        colw = (epw - gap) / 2
        scorer_rows = scorers[:5]
        box_h = max(30, 14 + max(len(scorer_rows), 1) * 5
                    + (5 if len(scorers) > len(scorer_rows) else 0))
        rx = lm + colw + gap

        def team_color(team):
            if team == "Home":
                return HOME_RGB
            if team == "Away":
                return AWAY_RGB
            return INK

        for x in (lm, rx):
            pdf.set_fill_color(*CARD)
            pdf.set_draw_color(*LINE)
            pdf.rect(x, y0, colw, box_h, style="DF")

        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*MUTED)
        pdf.set_xy(lm + 3, y0 + 2)
        pdf.cell(colw - 6, 5, "SCORING SUMMARY")
        y = y0 + 8
        if scorer_rows:
            for goal in scorer_rows:
                team = goal.get("team") or "-"
                pdf.set_xy(lm + 3, y)
                pdf.set_font("Helvetica", "B", 8)
                pdf.set_text_color(*MUTED)
                pdf.cell(17, 5, _pdf_safe(goal.get("time") or "-"))
                pdf.set_text_color(*team_color(team))
                pdf.cell(18, 5, _pdf_safe(team.upper()[:8]))
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(*INK)
                pdf.cell(colw - 41, 5, _pdf_safe((goal.get("player")
                                                   or "Goal")[:30]))
                y += 5
            if len(scorers) > len(scorer_rows):
                pdf.set_xy(lm + 3, y)
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(*MUTED)
                pdf.cell(colw - 6, 5,
                         f"+{len(scorers) - len(scorer_rows)} more goals")
        else:
            pdf.set_xy(lm + 3, y)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(*MUTED)
            pdf.cell(colw - 6, 5, "No goals recorded")

        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*MUTED)
        pdf.set_xy(rx + 3, y0 + 2)
        pdf.cell(colw - 6, 5, "PLAYER OF THE MATCH")
        if potm:
            name, block, score = potm
            team = block.get("Team") or "-"
            pdf.set_xy(rx + 3, y0 + 8)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(*team_color(team))
            pdf.cell(colw - 6, 6, _pdf_safe(name[:34]))
            pdf.set_xy(rx + 3, y0 + 15)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(*MUTED)
            pdf.cell(colw - 6, 5, _pdf_safe(f"{team}  |  Impact {score}"))
            bits = []
            for key, label in (
                ("Goals", "G"), ("On Target", "SOT"), ("Saves", "SV"),
                ("Tackles", "TKL"), ("Events", "EV"),
            ):
                value = block.get(key, 0)
                if value:
                    bits.append(f"{value} {label}")
            pdf.set_xy(rx + 3, y0 + 21)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(*INK)
            pdf.cell(colw - 6, 5, _pdf_safe(", ".join(bits)[:52]))
        else:
            pdf.set_xy(rx + 3, y0 + 8)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(*MUTED)
            pdf.cell(colw - 6, 5, "No standout selected")

        pdf.set_y(y0 + box_h + 4)

    # ---- Possession & efficiency (boxed) ---------------------------------- #
    section("Possession & Efficiency")
    y0 = pdf.get_y()
    pdf.ln(2)
    bx, by, bh = lm + 4, pdf.get_y(), 7
    bw = epw - 8
    hw = bw * (hp / 100.0)
    pdf.set_fill_color(*HOME_RGB)
    pdf.rect(bx, by, hw, bh, style="F")
    pdf.set_fill_color(*AWAY_RGB)
    pdf.rect(bx + hw, by, bw - hw, bh, style="F")
    pdf.set_xy(bx, by)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(hw, bh, f" Home {hp}%", align="L")
    pdf.cell(bw - hw, bh, f"Away {ap}% ", align="R")
    pdf.ln(bh + 2)
    leader, _strength = IN.momentum_leader(events,
                                           vision_weight=_vision_weight(vision))
    momentum = f"{leader} finished stronger" if leader else "Even"
    home_extra, away_extra = _derived_stats(home), _derived_stats(away)
    pdf.set_x(lm + 4)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, _pdf_safe(
        f"Shot accuracy: Home {home_extra['Shot Accuracy %']}%  /  Away "
        f"{away_extra['Shot Accuracy %']}%"),
        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(lm + 4)
    pdf.cell(0, 6, _pdf_safe(
        f"Shot conversion: Home {_conversion(home)}%  /  Away "
        f"{_conversion(away)}%        Momentum: {momentum}"),
        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    frame(y0)
    pdf.ln(3)

    # ---- Vision (the Eye) -------------------------------------------------- #
    # Shown as its OWN series next to the audio figures above, never blended
    # into them. When the two disagree that disagreement is information; folding
    # a low-confidence vision number into the headline stat would destroy it.
    if vision:
        q = vision.get("quality") or {}
        section("Camera Analysis")
        y0 = pdf.get_y()
        pdf.ln(2)
        pdf.set_x(lm + 4)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*INK)
        pdf.cell(0, 6, _pdf_safe(f"Reliability: {q.get('label', 'Unusable')}"),
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_x(lm + 4)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(epw - 8, 5, _pdf_safe(q.get("blurb", "")))

        if vision.get("usable"):
            vh, va = vision["possession"]
            pdf.set_x(lm + 4)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*INK)
            pdf.cell(0, 6, _pdf_safe(
                f"Possession seen by camera: Home {vh:.0f}%  /  Away {va:.0f}%"),
                new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_x(lm + 4)
            pdf.set_text_color(*MUTED)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(0, 5, _pdf_safe(
                f"Play-by-play possession above: Home {hp}%  /  Away {ap}%."
                f"        Passes detected: {vision.get('passes', 0)}"),
                new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            gap = abs(vh - hp)
            if gap >= 15:
                pdf.set_x(lm + 4)
                pdf.multi_cell(epw - 8, 5, _pdf_safe(
                    f"Note: the two methods differ by {gap:.0f} points. The "
                    f"camera measures ball proximity; the play-by-play counts "
                    f"logged events. Treat the gap as a prompt to review, not "
                    f"as an error."))
        pdf.set_x(lm + 4)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(epw - 8, 5, _pdf_safe("Why: " + "; ".join(
            q.get("reasons") or ["no detail recorded"]) + "."))
        pdf.ln(1)
        frame(y0)
        pdf.ln(3)

    # ---- Expected goals ----------------------------------------------------- #
    # A published geometric model, printed with its own caveat. It is a way of
    # comparing chances, not a claim about how many goals should have been
    # scored, and the report says so rather than leaving the reader to assume.
    try:
        from analytics.derived_metrics import match_summary as _derived

        derived = _derived(events)
    except Exception:
        derived = {}

    xg_home = (derived.get("Home") or {}).get("expected_goals") or {}
    xg_away = (derived.get("Away") or {}).get("expected_goals") or {}
    if xg_home.get("shots") or xg_away.get("shots"):
        section("Expected Goals")
        y0 = pdf.get_y()
        pdf.ln(2)
        pdf.set_x(lm + 4)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*INK)
        pdf.cell(0, 7, _pdf_safe(
            f"Home {xg_home.get('xg', 0):.2f}    -    "
            f"Away {xg_away.get('xg', 0):.2f}"),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_x(lm + 4)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(epw - 8, 4.6, _pdf_safe(
            f"From {xg_home.get('shots', 0)} and {xg_away.get('shots', 0)} "
            f"attempts, using {xg_home.get('model', 'the model')}. This is a "
            f"model, not a measurement: a way of comparing the quality of "
            f"chances, not the number of goals that should have been scored."))
        weakest = xg_home.get("provenance") or xg_away.get("provenance")
        if weakest == "no_geometry":
            pdf.set_x(lm + 4)
            pdf.multi_cell(epw - 8, 4.6, _pdf_safe(
                "Most attempts were logged without a location, so these totals "
                "rest on an average conversion rate rather than on where each "
                "shot was taken. Saying where a shot came from would sharpen "
                "this considerably."))
        elif weakest == "zone_estimate":
            pdf.set_x(lm + 4)
            pdf.multi_cell(epw - 8, 4.6, _pdf_safe(
                "Shot positions came from described zones, so these are "
                "accurate to a zone rather than to a metre."))
        pdf.ln(1)
        frame(y0)
        pdf.ln(3)

    # ---- Possession quality ------------------------------------------------ #
    # Raw possession share says who held the ball; these say what they did with
    # it. Reconstructed from the event stream, so it works on a voice-logged
    # match today and sharpens as vision adds events.
    try:
        from football import possessions as POSS
        from football.zones import enrich_all

        poss_summary = POSS.summarise(enrich_all(events))
    except Exception:
        poss_summary = {}

    if poss_summary:
        section("Possession Quality")
        y0 = pdf.get_y()
        pdf.ln(2)
        pdf.set_x(lm + 4)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 6, _pdf_safe(
            "How each side used the ball, not just how long they held it."),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        for side, label in (("Home", "Home"), ("Away", "Away")):
            row = poss_summary.get(side)
            if not row:
                continue
            pdf.set_x(lm + 4)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*INK)
            pdf.cell(0, 6, _pdf_safe(label), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_x(lm + 8)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*MUTED)
            pdf.cell(0, 5.5, _pdf_safe(
                f"{row['possessions']} possessions  ·  "
                f"{row['shot_rate']:.0f}% ended in a shot  ·  "
                f"{row['passes_per_possession']:.1f} passes each  ·  "
                f"{row['set_piece_starts']} began from a set piece"),
                new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)
        frame(y0)
        pdf.ln(3)

    # ---- Momentum graph --------------------------------------------------- #
    if momentum_png and os.path.exists(momentum_png):
        section("Match Momentum")
        try:
            from PIL import Image
            with Image.open(momentum_png) as im:
                iw, ih = im.size
            w = epw
            h = w * ih / iw
            y0 = pdf.get_y()
            pdf.image(momentum_png, x=lm, y=y0, w=w, h=h)
            pdf.set_draw_color(*LINE)
            pdf.rect(lm, y0, w, h)
            pdf.set_y(y0 + h + 3)
        except Exception:
            pass

    # ---- Starting lineups (optional) -------------------------------------- #
    if control.has_lineups(lineups):
        hl = _roster_lines(lineups, "Home")
        al = _roster_lines(lineups, "Away")
        section("Starting Lineups")
        colw = epw / 2
        pdf.set_x(lm)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*HOME_RGB)
        pdf.cell(colw, 6, _pdf_safe(_lineup_heading(lineups, "Home")),
                 border="B", align="L")
        pdf.set_text_color(*AWAY_RGB)
        pdf.cell(colw, 6, _pdf_safe(_lineup_heading(lineups, "Away")),
                 border="B", align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*INK)
        for i in range(max(len(hl), len(al))):
            h = hl[i] if i < len(hl) else ""
            a = al[i] if i < len(al) else ""
            pdf.set_x(lm)
            pdf.cell(colw, 5, _pdf_safe(h[:48]), align="L")
            pdf.cell(colw, 5, _pdf_safe(a[:48]), align="L",
                     new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)

    # ---- Team stats (boxed, shaded rows) ---------------------------------- #
    section("Team Stats")
    y0 = pdf.get_y()
    pdf.set_x(lm)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*NAVY_RGB)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(epw * 0.25, 7, "HOME", align="C", fill=True)
    pdf.cell(epw * 0.50, 7, "STATISTIC", align="C", fill=True)
    pdf.cell(epw * 0.25, 7, "AWAY", align="C", fill=True,
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    fill = False
    for k, h_val, a_val in _team_stats_rows(data)[1:]:
        pdf.set_x(lm)
        pdf.set_fill_color(*(SHADE if fill else (255, 255, 255)))
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*HOME_RGB)
        pdf.cell(epw * 0.25, 7, str(h_val), align="C", fill=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*INK)
        pdf.cell(epw * 0.50, 7, _pdf_safe(k), align="C", fill=True)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*AWAY_RGB)
        pdf.cell(epw * 0.25, 7, str(a_val), align="C", fill=True,
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        fill = not fill
    frame(y0)
    pdf.ln(3)

    # ---- By half (boxed, grouped Home/Away per half) ---------------------- #
    h1, h2 = data["home_halves"], data["away_halves"]
    section("By Half")
    y0 = pdf.get_y()
    pdf.set_x(lm)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*NAVY_RGB)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(epw * 0.32, 6, "", align="L", fill=True)
    pdf.cell(epw * 0.34, 6, "1st Half", align="C", fill=True)
    pdf.cell(epw * 0.34, 6, "2nd Half", align="C", fill=True,
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(lm)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(*SHADE)
    pdf.set_text_color(*MUTED)
    pdf.cell(epw * 0.32, 5, " Statistic", align="L", fill=True)
    for _ in range(2):
        pdf.set_text_color(*HOME_RGB)
        pdf.cell(epw * 0.17, 5, "Home", align="C", fill=True)
        pdf.set_text_color(*AWAY_RGB)
        pdf.cell(epw * 0.17, 5, "Away", align="C", fill=True)
    pdf.ln(5)
    fill = False
    for k in HALF_STAT_KEYS:
        pdf.set_x(lm)
        pdf.set_fill_color(*(SHADE if fill else (255, 255, 255)))
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*INK)
        pdf.cell(epw * 0.32, 6, _pdf_safe(" " + k), align="L", fill=True)
        for hh, aa in (
            _half_stat_pair(h1["1st"], h2["1st"], k),
            _half_stat_pair(h1["2nd"], h2["2nd"], k),
        ):
            pdf.set_text_color(*HOME_RGB)
            pdf.cell(epw * 0.17, 6, str(hh), align="C", fill=True)
            pdf.set_text_color(*AWAY_RGB)
            pdf.cell(epw * 0.17, 6, str(aa), align="C", fill=True)
        pdf.ln(6)
        fill = not fill
    frame(y0)
    pdf.ln(3)

    summary_lines = _post_match_summary_lines(events, data, summary)
    section("Post-Match Summary")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 6, _pdf_safe("\n".join(summary_lines)))
    pdf.ln(2)

    note_groups = _note_groups(notes, written_notes)
    for title, items in (("Audio Notes", note_groups["audio"]),
                         ("Written Notes", note_groups["written"])):
        if not items:
            continue
        section(title)
        for n in items:
            pdf.set_x(lm)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*MUTED)
            pdf.cell(epw * 0.14, 5, _pdf_safe(n.get("match_time") or ""),
                     align="L")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*INK)
            pdf.multi_cell(epw * 0.86, 5, _pdf_safe(n.get("text", "")),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)

    pdf.output(path)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
TEAM_LOGO_DIR = os.environ.get("KICKOFF_TEAM_LOGO_DIR", "branding/teams")


def _default_logo(side: str):
    """branding/teams/home.* (or away.*) if the user dropped a crest there."""
    for ext in ("png", "jpg", "jpeg", "webp"):
        p = os.path.join(TEAM_LOGO_DIR, f"{side}.{ext}")
        if os.path.exists(p):
            return p
    return None


def _slugify(name: str) -> str:
    """'Hub City FC vs Ristozi FC' -> 'Hub_City_FC_vs_Ristozi_FC'."""
    return re.sub(r"[^A-Za-z0-9]+", "_", str(name or "")).strip("_")


def _match_date(events) -> str:
    """Match date (YYYY-MM-DD) from the earliest event, else today."""
    for e in events:
        ts = e.get("timestamp")
        if ts:
            try:
                return datetime.fromisoformat(ts).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return datetime.now().strftime("%Y-%m-%d")


def generate(events=None, summary="", clock="", out_dir=None,
             data_file=None, archive=True, match_name="", lineups=None,
             notes=None, written_notes=None, home_logo=None, away_logo=None,
             vision=None, vision_stats=None) -> dict:
    """Generate txt + pdf reports (and archive data). Returns the paths.

    `home_logo`/`away_logo` are optional crest image paths; when omitted they
    default to branding/teams/home.* and away.* if present. `notes` are captured
    voice notes by default; pass `written_notes` for typed coach notes.

    `vision` is the camera-analysis block (see :func:`load_vision`); by default
    it is loaded from `vision_stats` / match_stats.json when that file exists.
    Pass `vision={}` to omit the camera section entirely.
    """
    out_dir = out_dir or REPORTS_DIR
    os.makedirs(out_dir, exist_ok=True)
    home_logo = home_logo or _default_logo("home")
    away_logo = away_logo or _default_logo("away")
    data_file = data_file or S.DATA_FILE
    if events is None:
        events = S.load_events(data_file)
    if notes is None:
        notes = control.load_notes()
    if vision is None:
        vision = load_vision(vision_stats)

    data = _collect(events)
    # Intuitive filename base: teams + match date, e.g.
    # "Hub_City_FC_vs_Ristozi_FC_2026-06-24".
    base = f"{_slugify(match_name) or 'match'}_{_match_date(events)}"

    txt_path = os.path.join(out_dir, f"{base}.txt")
    pdf_path = os.path.join(out_dir, f"{base}.pdf")
    png_path = os.path.join(out_dir, f"{base}_timeline.png")
    mom_path = os.path.join(out_dir, f"{base}_momentum.png")
    events_csv_path = os.path.join(out_dir, f"{base}_events.csv")
    team_csv_path = os.path.join(out_dir, f"{base}_team_stats.csv")
    player_csv_path = os.path.join(out_dir, f"{base}_player_stats.csv")
    stats_xlsx_path = os.path.join(out_dir, f"{base}_stats.xlsx")
    report_json_path = os.path.join(out_dir, f"{base}_report_payload.json")

    # Render the visual-timeline image as a standalone artifact (used by the
    # match library + downloads). It is intentionally NOT embedded in the PDF.
    score = (data["home"]["Goals"], data["away"]["Goals"])
    try:
        TL.render(events, score=score, clock=clock, path=png_path)
    except Exception:
        png_path = None

    # Render the momentum graph (embedded in the PDF + saved alongside).
    try:
        import momentum_image as MOM
        mom_path = MOM.render(events, mom_path,
                              vision_weight=_vision_weight(vision))
    except Exception:
        mom_path = None

    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(build_text(events, data, summary, clock, match_name, lineups,
                            notes, written_notes, vision=vision))
    build_pdf(events, data, summary, clock, pdf_path,
              match_name=match_name, lineups=lineups, notes=notes,
              written_notes=written_notes,
              momentum_png=mom_path, home_logo=home_logo, away_logo=away_logo,
              vision=vision)
    with open(report_json_path, "w", encoding="utf-8") as fh:
        json.dump(
            build_json_payload(events, data, summary, clock, match_name,
                               lineups, notes, written_notes),
            fh, ensure_ascii=False, separators=(",", ":"), default=str)

    # Spreadsheet-friendly data exports.
    for csv_path, content in (
        (events_csv_path, build_events_csv(events)),
        (team_csv_path, build_team_stats_csv(data)),
        (player_csv_path, build_player_stats_csv(data)),
    ):
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            fh.write(content)
    build_stats_xlsx(data, stats_xlsx_path)

    result = {
        "txt": txt_path, "pdf": pdf_path, "events": len(events),
        "events_csv": events_csv_path, "team_csv": team_csv_path,
        "players_csv": player_csv_path, "stats_xlsx": stats_xlsx_path,
        "report_json": report_json_path,
    }
    if png_path and os.path.exists(png_path):
        result["image"] = png_path
    if mom_path and os.path.exists(mom_path):
        result["momentum"] = mom_path
    if archive and os.path.exists(data_file):
        archive_path = os.path.join(out_dir, f"{base}_data.json")
        shutil.copyfile(data_file, archive_path)
        result["data"] = archive_path
    return result


if __name__ == "__main__":
    import control
    state = control.load_control()
    main_clk, added, half = control.clock_label(state["timer"])
    clock = f"{main_clk}{(' ' + added) if added else ''} ({half})"
    paths = generate(summary=state.get("summary", ""), clock=clock,
                     match_name=state.get("match_name", ""),
                     lineups=state.get("lineups"))
    print("Report written:")
    for k, v in paths.items():
        print(f"  {k}: {v}")
