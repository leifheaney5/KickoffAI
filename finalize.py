#!/usr/bin/env python3
"""
Kickoff Pulse — finalize a match into the library.

Snapshots the current live match (report bundle, data exports, audio notes,
vision output, and optionally a video clip) into its own library folder, mirrors
the event log into Postgres, and returns the new match's slug.

This is the bridge between the live, single-match working files (match_data.json,
notes_audio/, match_stats.json) and the permanent, browsable library.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from datetime import date, datetime
from typing import Optional

import control
import db
import library
import report
import stats as S

# report.generate() result key -> (media kind, human label)
_REPORT_ARTIFACTS = {
    "pdf": ("report_pdf", "Match report (PDF)"),
    "txt": ("report_txt", "Match report (text)"),
    "image": ("timeline_png", "Timeline image"),
    "events_csv": ("events_csv", "Events (CSV)"),
    "team_csv": ("team_csv", "Team stats (CSV)"),
    "players_csv": ("player_csv", "Player stats (CSV)"),
    "data": ("data_json", "Raw match data (JSON)"),
}


def _parse_date(name: Optional[str]) -> date:
    """A leading YYYY-MM-DD in the match name, else today."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", name or "")
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return datetime.now().date()


def finalize_match(events=None, state=None, notes=None, clock: str = "",
                   video_path: Optional[str] = None) -> str:
    """Archive the current match into the library; return its slug.

    All inputs default to the live working files so the dashboard can call this
    with no arguments at the end of a match.
    """
    if state is None:
        state = control.load_control()
    if events is None:
        events = S.load_events()
    if notes is None:
        notes = control.load_notes()

    home = S.team_stats(events, "Home")
    away = S.team_stats(events, "Away")
    teams = state.get("teams", {})
    name = ((state.get("match_name") or "").strip()
            or datetime.now().strftime("Match %Y-%m-%d %H:%M"))
    home_team = teams.get("home", {}).get("name", "").strip()
    away_team = teams.get("away", {}).get("name", "").strip()
    played_on = _parse_date(state.get("match_name"))

    # Generate the full report bundle into a throwaway staging dir, then copy the
    # artifacts into the match's permanent folder.
    stage = tempfile.mkdtemp(prefix="kp_finalize_")
    try:
        paths = report.generate(
            events=events, summary=state.get("summary", ""), clock=clock,
            out_dir=stage, archive=True, match_name=name,
            lineups=state.get("lineups"))

        db.init_db()
        with db.session() as s:
            match = library.create_match(
                s, name, played_on, home_team, away_team,
                home["Goals"], away["Goals"], state.get("summary", ""))

            for key, (kind, label) in _REPORT_ARTIFACTS.items():
                p = paths.get(key)
                if p:
                    library.register_file(s, match, kind, p, label)

            # Vision output, if a run produced one.
            if os.path.exists("match_stats.json"):
                library.register_file(s, match, "data_json", "match_stats.json",
                                      "Vision stats (JSON)")

            # Recorded voice notes (keep the originals).
            for n in notes:
                ap = n.get("audio")
                if ap and os.path.exists(ap):
                    label = (n.get("text") or "").strip()[:60] or "Voice note"
                    library.register_file(s, match, "audio_note", ap, label)

            # Optional match video (copied in so the match is self-contained).
            if video_path and os.path.exists(video_path):
                library.register_file(s, match, "video", video_path,
                                      "Match video")

            # Mirror the event log for cross-match querying.
            for e in events:
                s.add(db.Event(
                    match_id=match.id, match_time=e.get("match_time"),
                    team=e.get("team"), player=e.get("player"),
                    action=e.get("action"), result=e.get("result"),
                    location=e.get("location"), raw_text=e.get("raw_text")))

            return match.slug
    finally:
        shutil.rmtree(stage, ignore_errors=True)
