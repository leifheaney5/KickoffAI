#!/usr/bin/env python3
"""
Kickoff Pulse — match library database layer.

A thin, backend-agnostic SQLAlchemy layer that indexes every match and its
artifacts (reports, data, audio, images, video). Postgres is the intended
backend (see docker-compose.yml); when KICKOFF_DB_URL is unset it falls back to
a local SQLite file so the app runs with zero setup during development.

Storage model: this DB is the *index*. The actual files live on disk under the
match's library folder (see library.py); rows here point at them by relative
path. That keeps large media out of the database and makes zip export trivial.

Usage:
    import db
    db.init_db()                       # create tables
    with db.session() as s:            # transactional unit of work
        s.add(db.Match(slug="...", name="..."))
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (BigInteger, Date, DateTime, ForeignKey, Integer,
                        String, Text, Uuid, create_engine)
from sqlalchemy.orm import (DeclarativeBase, Mapped, Session, mapped_column,
                            relationship, sessionmaker)

# Postgres when KICKOFF_DB_URL is set (docker-compose provides it); otherwise a
# local SQLite file so nothing external is required to run the app.
DEFAULT_SQLITE_URL = "sqlite:///library.db"
DB_URL = os.environ.get("KICKOFF_DB_URL", DEFAULT_SQLITE_URL)

_engine = None
_Session: Optional[sessionmaker] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Match(Base):
    """A single match — the first-class entity everything else hangs off."""

    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                          default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300), default="")
    competition: Mapped[str] = mapped_column(String(200), default="")
    played_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    home_team: Mapped[str] = mapped_column(String(120), default="")
    away_team: Mapped[str] = mapped_column(String(120), default="")
    home_score: Mapped[int] = mapped_column(Integer, default=0)
    away_score: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_utcnow,
                                                 onupdate=_utcnow)

    events: Mapped[list["Event"]] = relationship(
        back_populates="match", cascade="all, delete-orphan")
    media: Mapped[list["MediaFile"]] = relationship(
        back_populates="match", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Match {self.slug!r} {self.home_score}-{self.away_score}>"


class Event(Base):
    """A mirrored event-log row, queryable across matches for season stats."""

    __tablename__ = "events"

    # BigInteger on Postgres, but SQLite only autoincrements INTEGER PRIMARY KEY,
    # so fall back to Integer there via a dialect variant.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True)
    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    match_time: Mapped[Optional[str]] = mapped_column(String(16))
    team: Mapped[Optional[str]] = mapped_column(String(16))
    player: Mapped[Optional[str]] = mapped_column(String(120))
    action: Mapped[Optional[str]] = mapped_column(String(40))
    result: Mapped[Optional[str]] = mapped_column(String(40))
    location: Mapped[Optional[str]] = mapped_column(String(120))
    raw_text: Mapped[Optional[str]] = mapped_column(Text)

    match: Mapped["Match"] = relationship(back_populates="events")


# Recognised artifact kinds — the UI groups and previews by these.
MEDIA_KINDS = (
    "report_pdf", "report_txt", "events_csv", "team_csv", "player_csv",
    "data_json", "timeline_png", "audio_note", "image", "video",
)


class MediaFile(Base):
    """One artifact belonging to a match; `path` is relative to the library root."""

    __tablename__ = "media_files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                          default=uuid.uuid4)
    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    path: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(200), default="")
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_utcnow)

    match: Mapped["Match"] = relationship(back_populates="media")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<MediaFile {self.kind} {self.path!r}>"


def get_engine():
    """Lazily build the engine + session factory (one per process)."""
    global _engine, _Session
    if _engine is None:
        # SQLite needs check_same_thread off for Streamlit's threading model.
        connect_args = ({"check_same_thread": False}
                        if DB_URL.startswith("sqlite") else {})
        _engine = create_engine(DB_URL, future=True, pool_pre_ping=True,
                                connect_args=connect_args)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


# Columns added after the first release — applied idempotently to existing
# tables so a DB created before they existed picks them up without a migration
# framework. (table, column, SQL type, default literal)
_ADDED_COLUMNS = [
    ("matches", "competition", "VARCHAR(200)", "''"),
]


def _apply_migrations(engine) -> None:
    """Add any missing post-release columns to existing tables (idempotent)."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    for table, column, sqltype, default in _ADDED_COLUMNS:
        if table not in existing_tables:
            continue  # create_all will build it fresh with the column present
        cols = {c["name"] for c in insp.get_columns(table)}
        if column not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {column} {sqltype} "
                    f"DEFAULT {default}"))


def init_db() -> None:
    """Create all tables if they don't yet exist, then apply column migrations."""
    engine = get_engine()
    _apply_migrations(engine)        # ALTER existing tables before/independent of
    Base.metadata.create_all(engine)  # create_all for any brand-new tables


@contextmanager
def session() -> Session:
    """Transactional session scope: commits on success, rolls back on error."""
    get_engine()
    assert _Session is not None
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


if __name__ == "__main__":
    init_db()
    print(f"Initialized Kickoff Pulse library schema at: {DB_URL}")
