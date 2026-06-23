#!/usr/bin/env python3
"""
Kickoff Pulse — shared control state.

A tiny JSON file (control.json) that the dashboard writes and the audio tracker
reads. It holds:
  - paused:  whether the tracker should stop logging new events
  - timer:   the match clock (running flag, start time, accumulated seconds, half)
  - summary: the post-match summary notes
"""

import json
import os
import tempfile
import time

CONTROL_FILE = os.environ.get("KICKOFF_CONTROL_FILE", "control.json")

# Live tracker status — written ONLY by audio_tracker, read by the dashboard.
# Kept in a separate file from control.json so the two processes never race on
# the same writer.
STATUS_FILE = os.environ.get("KICKOFF_STATUS_FILE", "status.json")

# Free-form match notes ("record thoughts"). Appended by the tracker while
# thoughts mode is on; read (and pruned) by the dashboard. Each note may keep
# its source audio clip in NOTES_AUDIO_DIR for playback under Match Insights.
NOTES_FILE = os.environ.get("KICKOFF_NOTES_FILE", "notes.json")
NOTES_AUDIO_DIR = os.environ.get("KICKOFF_NOTES_AUDIO_DIR", "notes_audio")

FIRST_HALF_SECONDS = 45 * 60
FULL_TIME_SECONDS = 90 * 60

# Background block-out: a 0-100 slider maps linearly onto this energy-threshold
# range (speech_recognition RMS units). 0 = very sensitive, 100 = only loud,
# close speech passes.
NOISE_GATE_MIN = 100.0
NOISE_GATE_MAX = 5000.0
DEFAULT_NOISE_GATE = 30


def gate_to_threshold(gate) -> float:
    """Map a 0-100 block-out strength to a mic energy threshold."""
    try:
        g = float(gate)
    except (TypeError, ValueError):
        g = DEFAULT_NOISE_GATE
    g = max(0.0, min(100.0, g))
    return NOISE_GATE_MIN + (NOISE_GATE_MAX - NOISE_GATE_MIN) * (g / 100.0)


def atomic_replace(tmp: str, dst: str, attempts: int = 40,
                   delay: float = 0.05) -> None:
    """os.replace, retried for Windows.

    On POSIX, renaming over an open file is fine. On Windows a process that has
    the destination open for reading (the dashboard polls these JSON files
    constantly) makes the rename fail with PermissionError/WinError 5. Those
    reads are sub-millisecond, so a short retry loop clears the contention.
    """
    for i in range(attempts):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)

DEFAULT = {
    "paused": False,
    "match_name": "",
    # Structured match metadata (drives the library record + analytics).
    "competition": "",
    "match_date": "",   # ISO YYYY-MM-DD; blank = use today when finalizing
    "timer": {
        "running": False,
        "start_epoch": None,   # wall-clock time when the clock was last started
        "accumulated": 0.0,    # seconds banked before the current run
        "second_half": False,
    },
    "summary": "",
    "teams": {
        "home": {"name": "", "lineup": ""},
        "away": {"name": "", "lineup": ""},
    },
    "thoughts_mode": False,
    "noise_gate": 30,
    "lineups": {
        "Home": {"formation": "", "players": []},
        "Away": {"formation": "", "players": []},
    },
}


def load_control() -> dict:
    """Load control state, filling in any missing defaults."""
    data = {}
    if os.path.exists(CONTROL_FILE):
        try:
            with open(CONTROL_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (ValueError, OSError):
            data = {}
    merged = {**DEFAULT, **(data if isinstance(data, dict) else {})}
    merged["timer"] = {**DEFAULT["timer"], **merged.get("timer", {})}
    saved_teams = merged.get("teams", {})
    merged["teams"] = {
        "home": {**DEFAULT["teams"]["home"], **saved_teams.get("home", {})},
        "away": {**DEFAULT["teams"]["away"], **saved_teams.get("away", {})},
    }
    merged["lineups"] = _normalise_lineups(merged.get("lineups"))
    return merged


def save_control(state: dict) -> None:
    """Atomically write control state."""
    directory = os.path.dirname(os.path.abspath(CONTROL_FILE)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        atomic_replace(tmp, CONTROL_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# --------------------------------------------------------------------------- #
# Lineups / roster
# --------------------------------------------------------------------------- #
def _normalise_lineups(lineups) -> dict:
    """Coerce stored lineups into the canonical {team: {formation, players}}."""
    out = {}
    src = lineups if isinstance(lineups, dict) else {}
    for team in ("Home", "Away"):
        t = src.get(team)
        if isinstance(t, dict):
            players = [p for p in (t.get("players") or []) if isinstance(p, dict)]
            out[team] = {"formation": str(t.get("formation") or ""),
                         "players": players}
        else:
            out[team] = {"formation": "", "players": []}
    return out


def roster_for(lineups, team) -> list:
    """The list of {number, name} dicts for a team (possibly empty)."""
    t = (lineups or {}).get(team)
    if isinstance(t, dict):
        return [p for p in (t.get("players") or []) if isinstance(p, dict)]
    return []


def lineup_formation(lineups, team) -> str:
    t = (lineups or {}).get(team)
    return str(t.get("formation") or "") if isinstance(t, dict) else ""


def has_lineups(lineups) -> bool:
    return any(roster_for(lineups, t) for t in ("Home", "Away"))


def resolve_player(lineups, player, team=None):
    """Resolve a parsed player reference against the roster.

    `player` is the tracker's canonical form ("#6" for a shirt number, else a
    name). Returns (name, team): a shirt number is mapped to that player's name
    and, when the side wasn't stated, the team is inferred — but only when the
    match is unambiguous across both rosters. Falls back to the inputs.
    """
    if not player or not has_lineups(lineups):
        return player, team
    num = player[1:] if player.startswith("#") and player[1:].isdigit() else None
    matches = []  # (team, name)
    for t in ("Home", "Away"):
        if team and t != team:
            continue
        for p in roster_for(lineups, t):
            pname = str(p.get("name") or "").strip()
            pnum = str(p.get("number") or "").strip()
            if num is not None:
                if pnum and pnum == num:
                    matches.append((t, pname or player))
            elif pname and pname.lower() == player.lower():
                matches.append((t, pname))
    if len(matches) == 1:
        mteam, mname = matches[0]
        return (mname or player), (team or mteam)
    return player, team


def roster_prompt(lineups) -> str:
    """A compact roster summary to hand the model as parsing context."""
    if not has_lineups(lineups):
        return ""
    blocks = []
    for team in ("Home", "Away"):
        roster = roster_for(lineups, team)
        if not roster:
            continue
        entries = ", ".join(
            f"#{str(p.get('number') or '').strip()} "
            f"{str(p.get('name') or '').strip()}".strip()
            for p in roster if (p.get("number") or p.get("name")))
        form = lineup_formation(lineups, team)
        head = team + (f" [{form}]" if form else "")
        blocks.append(f"{head}: {entries}")
    return "\n".join(blocks)


# --------------------------------------------------------------------------- #
# Timer helpers
# --------------------------------------------------------------------------- #
def elapsed_seconds(timer: dict) -> float:
    """Total seconds the clock has counted, including any in-progress run."""
    secs = float(timer.get("accumulated", 0.0))
    if timer.get("running") and timer.get("start_epoch"):
        secs += time.time() - timer["start_epoch"]
    return secs


def clock_label(timer: dict):
    """
    Return (main, added, half) where:
      main  = "MM:SS" capped at the current half boundary (45:00 / 90:00)
      added = "+M:SS" stoppage time beyond the boundary, or "" if none
      half  = "1st Half" / "2nd Half"
    """
    secs = elapsed_seconds(timer)
    second_half = timer.get("second_half", False)
    boundary = FULL_TIME_SECONDS if second_half else FIRST_HALF_SECONDS

    if secs <= boundary:
        main_secs, added_secs = secs, 0
    else:
        main_secs, added_secs = boundary, secs - boundary

    def fmt(s):
        s = int(s)
        return f"{s // 60:02d}:{s % 60:02d}"

    added = f"+{fmt(added_secs)}" if added_secs > 0 else ""
    half = "2nd Half" if second_half else "1st Half"
    return fmt(main_secs), added, half


# --------------------------------------------------------------------------- #
# Timer state transitions (return the mutated state; caller saves it)
# --------------------------------------------------------------------------- #
def timer_start(state: dict) -> dict:
    t = state["timer"]
    if not t["running"]:
        t["running"] = True
        t["start_epoch"] = time.time()
    return state


def timer_pause(state: dict) -> dict:
    t = state["timer"]
    if t["running"]:
        t["accumulated"] = elapsed_seconds(t)
        t["running"] = False
        t["start_epoch"] = None
    return state


def timer_reset(state: dict) -> dict:
    state["timer"] = dict(DEFAULT["timer"])
    return state


def timer_halftime(state: dict) -> dict:
    """Snap to 45:00, pause, and switch to the second half."""
    state["timer"] = {
        "running": False,
        "start_epoch": None,
        "accumulated": float(FIRST_HALF_SECONDS),
        "second_half": True,
    }
    return state


# --------------------------------------------------------------------------- #
# Live tracker status (audio_tracker writes, dashboard reads)
# --------------------------------------------------------------------------- #
def load_status() -> dict:
    if not os.path.exists(STATUS_FILE):
        return {}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def save_status(status: dict) -> None:
    status = {**status, "updated": time.time()}
    directory = os.path.dirname(os.path.abspath(STATUS_FILE)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(status, fh)
        atomic_replace(tmp, STATUS_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def record_seconds(status: dict) -> float:
    """Active recording time (banked + the current running stretch)."""
    secs = float(status.get("rec_accum", 0.0))
    if status.get("recording") and status.get("rec_since"):
        secs += time.time() - status["rec_since"]
    return secs


# --------------------------------------------------------------------------- #
# Match notes ("record thoughts / synopsis")
# --------------------------------------------------------------------------- #
def _write_json_atomic(data, path: str) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        atomic_replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load_notes(path: str = None) -> list:
    path = path or NOTES_FILE
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def append_note(note: dict, path: str = None) -> None:
    """Append a note (re-reading first so concurrent writes don't clobber)."""
    path = path or NOTES_FILE
    notes = load_notes(path)
    notes.append(note)
    _write_json_atomic(notes, path)


def delete_note(timestamp: str, path: str = None) -> bool:
    path = path or NOTES_FILE
    notes = load_notes(path)
    remaining = [n for n in notes if n.get("timestamp") != timestamp]
    if len(remaining) == len(notes):
        return False
    # Clean up the deleted note's audio clip, if any.
    for n in notes:
        if n.get("timestamp") == timestamp and n.get("audio"):
            try:
                if os.path.exists(n["audio"]):
                    os.remove(n["audio"])
            except OSError:
                pass
    _write_json_atomic(remaining, path)
    return True


def tracker_online(status: dict, max_age: float = 8.0) -> bool:
    """True if the tracker wrote its status recently enough to be considered live."""
    updated = status.get("updated")
    return bool(updated) and (time.time() - updated) < max_age


def fmt_clock(seconds: float) -> str:
    s = int(max(seconds, 0))
    return f"{s // 60:02d}:{s % 60:02d}"
