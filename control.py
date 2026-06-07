#!/usr/bin/env python3
"""
KickoffAI — shared control state.

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

FIRST_HALF_SECONDS = 45 * 60
FULL_TIME_SECONDS = 90 * 60


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
    "timer": {
        "running": False,
        "start_epoch": None,   # wall-clock time when the clock was last started
        "accumulated": 0.0,    # seconds banked before the current run
        "second_half": False,
    },
    "summary": "",
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


def tracker_online(status: dict, max_age: float = 8.0) -> bool:
    """True if the tracker wrote its status recently enough to be considered live."""
    updated = status.get("updated")
    return bool(updated) and (time.time() - updated) < max_age


def fmt_clock(seconds: float) -> str:
    s = int(max(seconds, 0))
    return f"{s // 60:02d}:{s % 60:02d}"
