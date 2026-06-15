#!/usr/bin/env python3
"""
Kickoff Pulse — match library: media store + match registration.

Sits on top of db.py. The DB is the index; this module owns the on-disk media
store. Every match gets a self-contained folder:

    library/<slug>/
        reports/   report_pdf, report_txt, timeline_png
        data/      data_json, events_csv, team_csv, player_csv
        audio/     audio_note
        images/    image
        video/     video

Because everything for a match lives under one folder, exporting a match is just
zipping that folder (see Phase 4). Paths stored in the DB are relative to
LIBRARY_ROOT so the store stays relocatable.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import date, datetime
from typing import Optional

import db

LIBRARY_ROOT = os.environ.get("KICKOFF_LIBRARY_ROOT", "library")

# Which subfolder each artifact kind lands in.
_KIND_DIR = {
    "report_pdf": "reports",
    "report_txt": "reports",
    "timeline_png": "reports",
    "data_json": "data",
    "events_csv": "data",
    "team_csv": "data",
    "player_csv": "data",
    "audio_note": "audio",
    "image": "images",
    "video": "video",
}


def slugify(name: str, played_on: Optional[date] = None) -> str:
    """A filesystem- and URL-safe slug, optionally date-prefixed.

    "Hub City FC vs FC Frederick" + 2026-06-10
        -> "2026-06-10-hub-city-fc-vs-fc-frederick"
    """
    base = re.sub(r"[^a-z0-9]+", "-", (name or "match").lower()).strip("-")
    base = base or "match"
    if played_on:
        return f"{played_on.isoformat()}-{base}"
    return base


def match_dir(slug: str) -> str:
    """Absolute path to a match's folder (created on demand)."""
    return os.path.join(LIBRARY_ROOT, slug)


def _ensure_tree(slug: str) -> str:
    root = match_dir(slug)
    for sub in ("reports", "data", "audio", "images", "video"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    return root


def _unique_slug(session, base_slug: str) -> str:
    """Append -2, -3, … if the slug is already taken."""
    slug = base_slug
    n = 2
    while session.query(db.Match).filter_by(slug=slug).first() is not None:
        slug = f"{base_slug}-{n}"
        n += 1
    return slug


def create_match(session, name: str, played_on: Optional[date] = None,
                 home_team: str = "", away_team: str = "",
                 home_score: int = 0, away_score: int = 0,
                 summary: str = "") -> db.Match:
    """Create a Match row (with a unique slug) and its on-disk folder tree.

    Caller supplies an open session; the row is added + flushed so `.id`/`.slug`
    are populated, but committing is left to the session scope.
    """
    played_on = played_on or datetime.now().date()
    slug = _unique_slug(session, slugify(name, played_on))
    match = db.Match(
        slug=slug, name=name or slug, played_on=played_on,
        home_team=home_team, away_team=away_team,
        home_score=home_score, away_score=away_score, summary=summary,
    )
    session.add(match)
    session.flush()
    _ensure_tree(slug)
    return match


def register_file(session, match: db.Match, kind: str, src_path: str,
                  label: str = "", copy: bool = True) -> Optional[db.MediaFile]:
    """Place a file in the match's store and index it.

    `kind` must be one of db.MEDIA_KINDS. Copies (or moves) `src_path` into the
    matching subfolder, then inserts a MediaFile row whose `path` is relative to
    LIBRARY_ROOT. Returns None if the source is missing.
    """
    if kind not in db.MEDIA_KINDS:
        raise ValueError(f"unknown media kind: {kind!r}")
    if not src_path or not os.path.exists(src_path):
        return None

    _ensure_tree(match.slug)
    sub = _KIND_DIR[kind]
    fname = os.path.basename(src_path)
    rel_path = os.path.join(match.slug, sub, fname)
    dest = os.path.join(LIBRARY_ROOT, rel_path)

    # Avoid clobbering a same-named file already in the store.
    if os.path.exists(dest) and os.path.abspath(dest) != os.path.abspath(src_path):
        stem, ext = os.path.splitext(fname)
        fname = f"{stem}_{int(datetime.now().timestamp())}{ext}"
        rel_path = os.path.join(match.slug, sub, fname)
        dest = os.path.join(LIBRARY_ROOT, rel_path)

    if copy:
        shutil.copy2(src_path, dest)
    else:
        shutil.move(src_path, dest)

    media = db.MediaFile(
        match_id=match.id, kind=kind, path=rel_path,
        label=label or fname, bytes=os.path.getsize(dest),
    )
    session.add(media)
    session.flush()
    return media


def abs_path(media: db.MediaFile) -> str:
    """Absolute path on disk for a stored MediaFile."""
    return os.path.join(LIBRARY_ROOT, media.path)
