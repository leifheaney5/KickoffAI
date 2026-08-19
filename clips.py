#!/usr/bin/env python3
"""
Kickoff Pulse — automatic match clips.

Nobody watches a 90-minute match video; everybody watches the goal. The app
already stores the video and stamps every event with a wall-clock time, so the
only missing piece was cutting between the two.

**Alignment.** The obvious approach — map the match clock onto video time —
breaks at half-time: the match clock stops at 45:00 while the video keeps
rolling, so every second-half event lands minutes early. Wall clock removes the
problem entirely:

    video_position = event_timestamp - recording_started_at

No offsets, no half-time correction, no assumption about when kickoff was. When
the app recorded the video itself, `started_at` is already known and alignment
needs no input at all; otherwise the anchor is derived once from a moment the
user can point at ("the first goal is at 12:30 in the video").

Everything except :func:`extract` is pure, so the interesting logic is testable
without ffmpeg or a video file.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import datetime, timezone

# What is worth cutting. A coach reviews goals and the moments around them, not
# every completed pass.
CLIP_ACTIONS = {
    "goal": ("GOAL", 10, 14),
    "red_card": ("Red card", 8, 8),
    "yellow_card": ("Yellow card", 6, 6),
    "card": ("Card", 6, 6),
    "shot": ("Shot", 8, 8),
    "save": ("Save", 6, 8),
    "penalty": ("Penalty", 10, 14),
}

# Fallback window (seconds before / after) for anything not listed above.
DEFAULT_PRE, DEFAULT_POST = 8, 12


# --------------------------------------------------------------------------- #
# Alignment
# --------------------------------------------------------------------------- #
def parse_ts(value) -> float | None:
    """An event's ISO timestamp as a POSIX float, or None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def anchor_from_recording(started_at: float) -> dict:
    """Alignment for a video the app recorded itself — exact, no input needed."""
    return {"started_at": float(started_at), "source": "recorder"}


def anchor_from_event(event: dict, video_seconds: float) -> dict | None:
    """Alignment derived from one event the user can point at in the video.

    Asking for the wall-clock time a recording began is unanswerable; asking
    "where is the first goal?" is not. Given that event and its position, the
    recording start follows.
    """
    ts = parse_ts(event.get("timestamp"))
    if ts is None:
        return None
    return {"started_at": ts - float(video_seconds), "source": "event"}


def video_position(event: dict, anchor: dict) -> float | None:
    """Where in the video this event happens, in seconds. None if unalignable."""
    if not anchor:
        return None
    ts = parse_ts(event.get("timestamp"))
    if ts is None:
        return None
    return ts - float(anchor.get("started_at", 0))


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "moment"


def clip_window(event: dict) -> tuple[str, int, int]:
    """(label, seconds_before, seconds_after) for an event."""
    action = (event.get("action") or "").lower()
    result = (event.get("result") or "").lower()
    if action == "card":
        action = "red_card" if "red" in result else "yellow_card"
    if result == "scored":
        action = "goal"
    label, pre, post = CLIP_ACTIONS.get(action,
                                        (action.title() or "Moment",
                                         DEFAULT_PRE, DEFAULT_POST))
    return label, pre, post


def is_clipworthy(event: dict) -> bool:
    """True for the events a coach actually reviews."""
    if event.get("status") == "denied":
        return False
    action = (event.get("action") or "").lower()
    result = (event.get("result") or "").lower()
    if action == "shot" and result not in ("on target", "saved", "scored"):
        return False          # a shot into row Z is not worth a clip
    return action in CLIP_ACTIONS or result == "scored"


def plan_clips(events, anchor: dict, duration: float = None,
               limit: int = 40) -> list[dict]:
    """What to cut, in match order, without cutting anything yet.

    Returned before extraction so the UI can show what will happen — and so a
    misaligned anchor is obvious (clips at negative or absurd positions) before
    ffmpeg spends minutes on it.

    Each entry: {label, name, start, end, event, match_time, team, ok, why}.
    """
    plan = []
    for e in events or []:
        if not is_clipworthy(e):
            continue
        pos = video_position(e, anchor)
        if pos is None:
            continue
        label, pre, post = clip_window(e)
        start = max(0.0, pos - pre)
        end = pos + post

        ok, why = True, ""
        if pos < 0:
            ok, why = False, "before the video starts"
        elif duration and pos > duration:
            ok, why = False, "after the video ends"
        elif duration:
            end = min(end, duration)

        who = e.get("player") or ""
        mt = (e.get("match_time") or "").replace(":", "-")
        name = "_".join(x for x in (mt, _slug(label), _slug(e.get("team")),
                                    _slug(who) if who else "") if x)
        plan.append({
            "label": label, "name": f"{name}.mp4",
            "start": round(start, 2), "end": round(end, 2),
            "match_time": e.get("match_time") or "",
            "team": e.get("team") or "", "player": who,
            "action": (e.get("action") or ""), "ok": ok, "why": why,
            "timestamp": e.get("timestamp"),
        })
        if len(plan) >= limit:
            break
    return plan


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def probe_duration(video: str) -> float | None:
    """Length of the video in seconds, or None if it cannot be read."""
    if not shutil.which("ffprobe") or not os.path.exists(video):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", video],
            capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def extract(plan, video: str, out_dir: str, reencode: bool = False,
            progress=None) -> dict:
    """Cut the planned clips out of ``video`` into ``out_dir``.

    A stream copy is fast but can only cut on a keyframe, so a clip may begin up
    to one GOP early — fine for review. ``reencode`` trades speed for a frame-
    accurate cut when that matters.
    """
    if not ffmpeg_available():
        return {"ok": False, "error": "ffmpeg is not installed.", "clips": []}
    if not os.path.exists(video):
        return {"ok": False, "error": f"No video at {video!r}.", "clips": []}

    os.makedirs(out_dir, exist_ok=True)
    made, failed = [], []
    usable = [c for c in plan if c["ok"]]
    for i, c in enumerate(usable):
        dest = os.path.join(out_dir, c["name"])
        cmd = ["ffmpeg", "-y",
               # -ss before -i seeks fast; the copy path needs it there anyway.
               "-ss", str(c["start"]), "-i", video,
               "-t", str(max(0.5, c["end"] - c["start"]))]
        cmd += (["-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                 "-c:a", "aac"] if reencode else ["-c", "copy"])
        cmd += [dest]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if res.returncode == 0 and os.path.exists(dest) \
                    and os.path.getsize(dest) > 0:
                made.append({**c, "path": dest,
                             "bytes": os.path.getsize(dest)})
            else:
                failed.append({**c, "error": (res.stderr or "")[-300:]})
        except (OSError, subprocess.SubprocessError) as exc:
            failed.append({**c, "error": str(exc)})
        if progress:
            progress((i + 1) / max(1, len(usable)), c["label"])

    return {"ok": True, "clips": made, "failed": failed,
            "skipped": [c for c in plan if not c["ok"]]}
