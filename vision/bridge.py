#!/usr/bin/env python3
"""Kickoff Pulse — vision → dashboard bridge.

Maps the computer-vision pipeline's ``match_stats.json`` onto the event schema
that the live dashboard / timeline already consume (the same shape the audio
tracker and Manual Entry page write). In other words: the Eye feeds the same UI
as the Ear.

Each vision *pass* becomes a dashboard event with ``action="pass"`` (which the
timeline renders with the Pass badge), carrying the outcome, the passer's team
and shirt number, the pass type, the pitch zone, and the raw coordinates for
drill-down. Possession is reported in the run summary (the current dashboard has
no possession widget to feed — see README).

Run it::

    # Idempotent augment: add/refresh vision passes in the dashboard's data file
    python -m vision.bridge --stats match_stats.json --out match_data.json

    # Or write just the vision events to a separate file to preview safely
    python -m vision.bridge --stats match_stats.json --out match_data.vision.json --fresh
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

# Make the repo-root modules importable no matter where this is launched from
# (mirrors how the Streamlit pages bootstrap their imports).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

SOURCE_TAG = "vision"


# --------------------------------------------------------------------------- #
# Token / time helpers
# --------------------------------------------------------------------------- #
def token_team(token: Optional[str]) -> Optional[str]:
    """``TeamA_No10`` -> ``Home``; ``TeamB_*`` -> ``Away``; else ``None``."""
    if not token:
        return None
    if token.startswith("TeamA"):
        return "Home"
    if token.startswith("TeamB"):
        return "Away"
    return None


def token_number(token: Optional[str]) -> Optional[int]:
    """Extract the shirt number from a ``..._No07`` token, else ``None``."""
    if not token or "_No" not in token:
        return None
    try:
        return int(token.split("_No", 1)[1])
    except (ValueError, IndexError):
        return None


def player_tag(token: Optional[str]) -> Optional[str]:
    """Dashboard player label, e.g. ``TeamA_No07`` -> ``#7`` (or ``None``)."""
    number = token_number(token)
    return f"#{number}" if number is not None else None


def video_seconds(timestamp: str) -> float:
    """Parse a ``MM:SS.s`` vision timestamp into seconds."""
    try:
        minutes, seconds = timestamp.split(":")
        return int(minutes) * 60 + float(seconds)
    except (ValueError, AttributeError):
        return 0.0


def match_time(seconds: float) -> str:
    """Format seconds as the dashboard's ``MM:SS`` match-clock string."""
    s = int(max(0.0, seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def pitch_zone(
    end_coords: Sequence[float], team: Optional[str], home_attacks_positive_x: bool = True
) -> Optional[str]:
    """Coarse human zone of a pass end point, relative to the team's attack."""
    if not end_coords:
        return None
    x = float(end_coords[0])
    if team == "Home":
        advancing = home_attacks_positive_x
    elif team == "Away":
        advancing = not home_attacks_positive_x
    else:
        return "midfield"
    advance = x if advancing else 100.0 - x
    if advance >= 66:
        return "attacking third"
    if advance <= 33:
        return "defensive third"
    return "midfield"


# --------------------------------------------------------------------------- #
# Conversion
# --------------------------------------------------------------------------- #
def pass_to_event(pass_dict: dict, kickoff: datetime) -> dict:
    """Convert one vision pass into a dashboard event record."""
    passer = pass_dict.get("passer")
    receiver = pass_dict.get("intended_receiver")
    team = token_team(passer)
    secs = video_seconds(pass_dict.get("timestamp", "00:00.0"))
    pass_type = pass_dict.get("pass_type", "pass")
    outcome = pass_dict.get("outcome", "completed")
    end_coords = pass_dict.get("end_coords") or [0.0, 0.0]

    receiver_label = player_tag(receiver) or (receiver if receiver else "?")
    return {
        "timestamp": (kickoff + timedelta(seconds=secs)).isoformat(),
        "match_time": match_time(secs),
        "raw_text": (
            f"vision: {pass_type.replace('_', ' ')} "
            f"{player_tag(passer) or passer or '?'} -> {receiver_label} ({outcome})"
        ),
        "status": "approved",
        "team": team,
        "player": player_tag(passer),
        "action": "pass",
        "result": outcome,
        "location": pitch_zone(end_coords, team),
        # --- provenance / extra detail (ignored by the stat table, shown in the
        #     timeline's detail expander) ---
        "source": SOURCE_TAG,
        "pass_type": pass_type,
        "receiver": receiver,
        "start_coords": pass_dict.get("start_coords"),
        "end_coords": end_coords,
        "event_id": pass_dict.get("event_id"),
    }


def convert(stats: dict, kickoff: Optional[datetime] = None) -> List[dict]:
    """Convert a full ``match_stats.json`` dict into dashboard events."""
    kickoff = kickoff or datetime.now(timezone.utc)
    passes = (
        stats.get("statistical_events", {}).get("passing_stats", []) or []
    )
    return [pass_to_event(p, kickoff) for p in passes]


def possession_of(stats: dict) -> Tuple[float, float]:
    summary = stats.get("statistical_events", {}).get("possession_summary", {})
    return (
        float(summary.get("team_home_percentage", 0.0)),
        float(summary.get("team_away_percentage", 0.0)),
    )


# --------------------------------------------------------------------------- #
# IO
# --------------------------------------------------------------------------- #
def _load_json(path: str) -> object:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_events(events: List[dict], path: str) -> None:
    """Write events using the app's own writer when available (best fidelity).

    Falls back to a self-contained atomic write so the bridge still works if the
    repo modules cannot be imported.
    """
    try:
        import stats as app_stats  # the dashboard's event IO

        app_stats.save_events(events, path)
        return
    except Exception:
        pass
    import tempfile

    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(events, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _load_existing(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    try:
        data = _load_json(path)
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def write_events(
    new_events: List[dict],
    out_path: str,
    fresh: bool = False,
    replace_vision: bool = True,
) -> List[dict]:
    """Merge ``new_events`` into ``out_path`` and return the final list.

    * ``fresh``           — ignore any existing file (write only the new events).
    * ``replace_vision``  — drop previously-bridged vision events first so a
                            re-run is idempotent (default).
    """
    existing = [] if fresh else _load_existing(out_path)
    if replace_vision:
        existing = [e for e in existing if e.get("source") != SOURCE_TAG]
    combined = existing + new_events
    combined.sort(key=lambda e: e.get("timestamp", ""))
    _save_events(combined, out_path)
    return combined


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m vision.bridge",
        description="Map vision match_stats.json passes into dashboard events.",
    )
    p.add_argument("--stats", default="match_stats.json", help="Vision stats JSON.")
    p.add_argument(
        "--out", default="match_data.json", help="Dashboard event file to update."
    )
    p.add_argument(
        "--fresh", action="store_true",
        help="Write only the vision events (ignore any existing file).",
    )
    p.add_argument(
        "--keep-old-vision", action="store_true",
        help="Do not drop previously-bridged vision events (default drops them).",
    )
    p.add_argument(
        "--kickoff", default=None,
        help="ISO-8601 kickoff time to anchor event timestamps (default: now).",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if not os.path.exists(args.stats):
        print(f"[bridge] stats file not found: {args.stats}", file=sys.stderr)
        return 1

    kickoff = None
    if args.kickoff:
        kickoff = datetime.fromisoformat(args.kickoff)
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)

    stats = _load_json(args.stats)
    events = convert(stats, kickoff)
    final = write_events(
        events,
        args.out,
        fresh=args.fresh,
        replace_vision=not args.keep_old_vision,
    )

    home, away = possession_of(stats)
    by_outcome: Dict[str, int] = {}
    for e in events:
        by_outcome[e["result"]] = by_outcome.get(e["result"], 0) + 1
    breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(by_outcome.items())) or "none"

    print(f"[bridge] converted {len(events)} pass event(s) [{breakdown}]")
    print(f"[bridge] possession (measured): Home {home:.1f}% / Away {away:.1f}%")
    print(f"[bridge] wrote {len(final)} total event(s) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
