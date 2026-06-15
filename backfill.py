#!/usr/bin/env python3
"""
Kickoff Pulse — backfill existing reports into the library.

One-off importer: scans the legacy reports/ directory, groups files by their
shared timestamp (e.g. match_report_20260610_205359.pdf), and registers each
group as a match in the library. Idempotent — re-running skips matches already
imported.

    python backfill.py            # import reports/ into the library
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

import db
import library
import stats as S

_TS_RE = re.compile(r"_(\d{8}_\d{6})\.")

# (filename prefix, extension) -> (media kind, label)
_FILE_KIND = [
    ("match_report_", ".pdf", "report_pdf", "Match report (PDF)"),
    ("match_report_", ".txt", "report_txt", "Match report (text)"),
    ("match_timeline_", ".png", "timeline_png", "Timeline image"),
    ("match_events_", ".csv", "events_csv", "Events (CSV)"),
    ("match_team_stats_", ".csv", "team_csv", "Team stats (CSV)"),
    ("match_player_stats_", ".csv", "player_csv", "Player stats (CSV)"),
    ("match_data_", ".json", "data_json", "Raw match data (JSON)"),
]


def _kind_for(fname: str):
    for prefix, ext, kind, label in _FILE_KIND:
        if fname.startswith(prefix) and fname.endswith(ext):
            return kind, label
    return None, None


def backfill_reports(reports_dir: str = None) -> list:
    """Import grouped report artifacts from `reports_dir`; return new slugs."""
    reports_dir = reports_dir or os.environ.get("KICKOFF_REPORTS_DIR", "reports")
    if not os.path.isdir(reports_dir):
        return []

    groups = {}
    for fname in os.listdir(reports_dir):
        m = _TS_RE.search(fname)
        if m:
            groups.setdefault(m.group(1), []).append(fname)

    db.init_db()
    created = []
    for ts, files in sorted(groups.items()):
        try:
            dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
        except ValueError:
            continue

        name = dt.strftime("Match %Y-%m-%d %H:%M")
        with db.session() as s:
            # Idempotent: skip a timestamp we've already imported.
            slug = library.slugify(name, dt.date())
            if s.query(db.Match).filter_by(slug=slug).first():
                continue

            # Recover events (for score + mirroring) from the archived JSON.
            events = []
            data_file = next((f for f in files if f.startswith("match_data_")
                              and f.endswith(".json")), None)
            if data_file:
                try:
                    with open(os.path.join(reports_dir, data_file)) as fh:
                        loaded = json.load(fh)
                    events = loaded if isinstance(loaded, list) else []
                except (ValueError, OSError):
                    events = []

            home = S.team_stats(events, "Home")
            away = S.team_stats(events, "Away")
            match = library.create_match(
                s, name, dt.date(),
                home_score=home["Goals"], away_score=away["Goals"])

            for fname in files:
                kind, label = _kind_for(fname)
                if kind:
                    library.register_file(s, match, kind,
                                          os.path.join(reports_dir, fname), label)

            for e in events:
                s.add(db.Event(
                    match_id=match.id, match_time=e.get("match_time"),
                    team=e.get("team"), player=e.get("player"),
                    action=e.get("action"), result=e.get("result"),
                    location=e.get("location"), raw_text=e.get("raw_text")))

            created.append(match.slug)
    return created


if __name__ == "__main__":
    slugs = backfill_reports()
    if slugs:
        print(f"Imported {len(slugs)} match(es):")
        for s in slugs:
            print(f"  {s}")
    else:
        print("Nothing new to import.")
