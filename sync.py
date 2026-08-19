#!/usr/bin/env python3
"""
Kickoff Pulse — push locally-archived matches to the club's shared library.

Capture must work with no signal at all: a pitch rarely has usable wifi, and a
match that fails because the server was unreachable is worse than no club
features. So archiving always writes to the **local** database first, and this
module pushes to the shared one whenever it happens to be reachable.

The design rests on one invariant: **`capture_id` is the identity of a match**.
It is minted on the capture machine (control.json's `match_id`) and travels with
the match, so pushing is idempotent — the same capture can never create two rows
on the server, however many times a flaky connection makes it retry.

    local    — archived here, never pushed
    pending  — a push was attempted and did not complete
    synced   — present on the shared server

Configuration:
    KICKOFF_DB_URL         the local library (as today)
    KICKOFF_SHARED_DB_URL  the club server; unset means "no club", and every
                           function here becomes a no-op
"""

from __future__ import annotations

import os

import db

SHARED_DB_URL = os.environ.get("KICKOFF_SHARED_DB_URL", "")

# Where the club's media lives — a mounted share, or a path on the server.
# `MediaFile.path` is already relative to a library root, so the same relative
# path works on both sides and nothing has to be rewritten.
SHARED_LIBRARY_ROOT = os.environ.get("KICKOFF_SHARED_LIBRARY_ROOT", "")

# Artifacts small enough to always be worth pushing: without them the club
# library has every number and none of the documents, which is the state that
# surprises the first coach who tries to open a colleague's report.
MEDIA_ALWAYS = ("report_pdf", "report_txt", "events_csv", "team_csv",
                "player_csv", "data_json", "timeline_png")

# Big artifacts. Off by default — pushing every match video would saturate club
# wifi, and the numbers are what people actually come for.
MEDIA_OPTIONAL = ("video", "audio_note", "image")

SYNC_MEDIA = os.environ.get("KICKOFF_SYNC_MEDIA", "1") not in ("0", "false", "no")
SYNC_LARGE_MEDIA = os.environ.get("KICKOFF_SYNC_VIDEO", "0") in ("1", "true", "yes")
# Skip any single file above this, whatever its kind, so one huge upload cannot
# stall a sync that would otherwise succeed. 0 disables the cap.
MEDIA_MAX_MB = float(os.environ.get("KICKOFF_SYNC_MEDIA_MAX_MB", "512"))

# Columns copied verbatim when a match is pushed. Deliberately explicit: adding a
# column to Match should be a conscious decision about whether it is shared.
_MATCH_FIELDS = (
    "slug", "name", "competition", "played_on", "home_team", "away_team",
    "home_score", "away_score", "summary",
    "vision_verdict", "vision_ball_rate", "vision_home_possession",
    "vision_away_possession", "vision_passes",
    "owner_id", "team_id", "capture_id",
)

_EVENT_FIELDS = ("match_time", "team", "player", "action", "result",
                 "location", "raw_text", "source")


def configured() -> bool:
    """True when a shared club server is configured."""
    return bool(SHARED_DB_URL.strip())


def _shared_sessionmaker():
    """A session factory for the shared server, with its schema ensured."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(SHARED_DB_URL, future=True, pool_pre_ping=True)
    db._apply_migrations(engine)
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True), engine


def server_reachable(timeout: float = 5.0) -> tuple[bool, str]:
    """(ok, detail). Never raises — being offline is the expected case."""
    if not configured():
        return False, "No shared server configured (KICKOFF_SHARED_DB_URL)."
    try:
        from sqlalchemy import text

        Session, engine = _shared_sessionmaker()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Connected."
    except Exception as exc:
        return False, f"Unreachable: {type(exc).__name__}: {exc}"


def pending_matches() -> list[dict]:
    """Locally-archived matches that are not yet on the shared server."""
    db.init_db()
    with db.session() as s:
        rows = (s.query(db.Match)
                .filter(db.Match.sync_state != "synced")
                .order_by(db.Match.played_on)
                .all())
        return [{"id": str(m.id), "slug": m.slug, "name": m.name,
                 "played_on": m.played_on, "sync_state": m.sync_state,
                 "capture_id": m.capture_id or "",
                 "events": len(m.events)} for m in rows]


def _copy_match(local_match, shared_session):
    """Insert or update one match on the shared server.

    Returns ``(action, remote_match)`` where action is 'created' or 'updated' —
    the row is handed back so media can be attached to it afterwards.

    Matching is by `capture_id` — never by slug, which two coaches could easily
    generate identically for different fixtures on the same day.
    """
    existing = None
    if local_match.capture_id:
        existing = (shared_session.query(db.Match)
                    .filter_by(capture_id=local_match.capture_id).first())

    if existing is None:
        remote = db.Match(sync_state="synced", synced_at=db._utcnow())
        for f in _MATCH_FIELDS:
            setattr(remote, f, getattr(local_match, f))
        # A slug collision on the server is possible when two coaches archive
        # different fixtures with the same teams and date; disambiguate rather
        # than fail the push.
        base, n = remote.slug, 2
        while shared_session.query(db.Match).filter_by(slug=remote.slug).first():
            remote.slug = f"{base}-{n}"
            n += 1
        shared_session.add(remote)
        shared_session.flush()
        action = "created"
    else:
        remote = existing
        for f in _MATCH_FIELDS:
            if f != "slug":            # keep the server's disambiguated slug
                setattr(remote, f, getattr(local_match, f))
        remote.sync_state = "synced"
        remote.synced_at = db._utcnow()
        # Replace the event log wholesale: it is derived from the capture, so
        # the local copy is authoritative and merging would risk duplicates.
        for e in list(remote.events):
            shared_session.delete(e)
        shared_session.flush()
        action = "updated"

    for e in local_match.events:
        shared_session.add(db.Event(
            match_id=remote.id,
            **{f: getattr(e, f) for f in _EVENT_FIELDS}))
    return action, remote


def media_to_push(local_match) -> tuple[list, list]:
    """(will_push, skipped) for one match's artifacts, with reasons.

    Returned rather than filtered silently, so the UI can say *why* a video did
    not travel instead of leaving the coach to wonder.
    """
    import library

    will, skipped = [], []
    for m in local_match.media:
        src = library.abs_path(m)
        if not os.path.exists(src):
            skipped.append((m, "missing on this machine"))
            continue
        size_mb = (m.bytes or os.path.getsize(src)) / (1024 * 1024)
        if m.kind in MEDIA_OPTIONAL and not SYNC_LARGE_MEDIA:
            skipped.append((m, f"{m.kind} not synced by default"))
        elif MEDIA_MAX_MB and size_mb > MEDIA_MAX_MB:
            skipped.append((m, f"{size_mb:.0f} MB is over the "
                               f"{MEDIA_MAX_MB:.0f} MB limit"))
        else:
            will.append(m)
    return will, skipped


def _copy_media(local_match, remote_match, shared_session) -> dict:
    """Copy a match's artifacts into the shared library and index them there.

    Runs *after* the match row has been committed, and its failures never roll
    that back: a 2 GB video over club wifi will be interrupted, and losing the
    match record because of it would be absurd. Individual files are skipped if
    already present at the same size, so an interrupted push resumes rather than
    starting over.
    """
    import shutil

    import library

    if not (SYNC_MEDIA and SHARED_LIBRARY_ROOT):
        return {"copied": 0, "skipped": 0, "reason": "media sync off"}

    will, skipped = media_to_push(local_match)
    copied = 0
    for m in will:
        src = library.abs_path(m)
        dest = os.path.join(SHARED_LIBRARY_ROOT, m.path)
        try:
            if not (os.path.exists(dest)
                    and os.path.getsize(dest) == os.path.getsize(src)):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(src, dest)
            existing = (shared_session.query(db.MediaFile)
                        .filter_by(match_id=remote_match.id, path=m.path)
                        .first())
            if existing is None:
                shared_session.add(db.MediaFile(
                    match_id=remote_match.id, kind=m.kind, path=m.path,
                    label=m.label, bytes=m.bytes))
            copied += 1
        except OSError as exc:
            skipped.append((m, f"copy failed: {exc}"))
    return {"copied": copied, "skipped": len(skipped),
            "reasons": [r for _m, r in skipped]}


def push(match_ids: list = None, dry_run: bool = False) -> dict:
    """Push pending matches to the shared server.

    Returns a report; never raises for the ordinary offline case, because being
    offline is normal and must not look like a failure.
    """
    if not configured():
        return {"ok": False, "error": "No shared server configured.",
                "pushed": 0, "results": []}

    ok, detail = server_reachable()
    if not ok:
        # Mark the attempt so the UI can distinguish "never tried" from
        # "tried and could not reach the server".
        if not dry_run:
            with db.session() as s:
                for m in s.query(db.Match).filter(db.Match.sync_state == "local"):
                    if match_ids is None or str(m.id) in set(match_ids):
                        m.sync_state = "pending"
        return {"ok": False, "error": detail, "pushed": 0, "results": [],
                "offline": True}

    Session, _engine = _shared_sessionmaker()
    results, pushed = [], 0

    db.init_db()
    with db.session() as local:
        query = local.query(db.Match).filter(db.Match.sync_state != "synced")
        if match_ids is not None:
            wanted = set(match_ids)
            matches = [m for m in query.all() if str(m.id) in wanted]
        else:
            matches = query.all()

        for m in matches:
            if dry_run:
                results.append({"slug": m.slug, "action": "would push"})
                continue
            shared = Session()
            try:
                action, remote = _copy_match(m, shared)
                shared.commit()
                m.sync_state = "synced"
                m.synced_at = db._utcnow()
                pushed += 1
                entry = {"slug": m.slug, "action": action}

                # Media is a separate, best-effort step: the match row is
                # already safe, and an interrupted file copy must not undo it.
                try:
                    media = _copy_media(m, remote, shared)
                    shared.commit()
                    entry["media"] = media
                except Exception as exc:
                    shared.rollback()
                    entry["media"] = {"copied": 0,
                                      "error": f"{type(exc).__name__}: {exc}"}
                results.append(entry)
            except Exception as exc:
                shared.rollback()
                m.sync_state = "pending"
                results.append({"slug": m.slug, "action": "failed",
                                "error": f"{type(exc).__name__}: {exc}"})
            finally:
                shared.close()

    return {"ok": True, "pushed": pushed, "results": results, "dry_run": dry_run}


def status() -> dict:
    """A summary for the UI: configured, reachable, and what is outstanding."""
    pending = pending_matches()
    reachable, detail = (server_reachable() if configured()
                         else (False, "No shared server configured."))
    return {
        "configured": configured(),
        "reachable": reachable,
        "detail": detail,
        "pending": len(pending),
        "matches": pending,
        "server": _redacted_url(),
    }


def _redacted_url() -> str:
    """The shared URL with any password removed, safe to show in the UI."""
    url = SHARED_DB_URL
    if not url:
        return ""
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(url)
        if parts.password:
            netloc = parts.netloc.replace(f":{parts.password}", ":***")
            parts = parts._replace(netloc=netloc)
        return urlunsplit(parts)
    except Exception:
        return "(configured)"
