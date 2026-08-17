#!/usr/bin/env bash
#
# Create a portable Kickoff backup: database dump + library media + live files.
#
# Usage:
#   scripts/backup_now.sh
#   KICKOFF_BACKUP_DIR=/Volumes/USB/KickoffBackups scripts/backup_now.sh

set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="${KICKOFF_BACKUP_DIR:-backups}"
LIBRARY_ROOT="${KICKOFF_LIBRARY_ROOT:-library}"
POSTGRES_CONTAINER="${KICKOFF_POSTGRES_CONTAINER:-kickoff-postgres}"
POSTGRES_USER="${KICKOFF_POSTGRES_USER:-kickoff}"
POSTGRES_DB="${KICKOFF_POSTGRES_DB:-kickoff}"
STAMP="$(date +%Y%m%d_%H%M%S)"
NAME="kickoff_backup_${STAMP}"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/${NAME}.XXXXXX")"

cleanup() {
  rm -rf "$STAGING"
}
trap cleanup EXIT

info() { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

postgres_running() {
  command -v docker >/dev/null 2>&1 &&
    docker inspect -f '{{.State.Running}}' "$POSTGRES_CONTAINER" 2>/dev/null |
    grep -q '^true$'
}

mkdir -p "$BACKUP_DIR"

{
  echo "created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "repo=$(pwd)"
  echo "library_root=$LIBRARY_ROOT"
  git rev-parse --short HEAD 2>/dev/null | sed 's/^/git_commit=/'
} > "$STAGING/metadata.txt"

if postgres_running; then
  info "Dumping Postgres database from $POSTGRES_CONTAINER..."
  docker exec "$POSTGRES_CONTAINER" pg_dump \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --clean --if-exists --no-owner --no-privileges |
    gzip -9 > "$STAGING/postgres.sql.gz"
  echo "db_backend=postgres" >> "$STAGING/metadata.txt"
  docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -At -c "select 'matches=' || count(*) from matches;" \
    -c "select 'events=' || count(*) from events;" \
    -c "select 'media_files=' || count(*) from media_files;" \
    >> "$STAGING/metadata.txt" 2>/dev/null || true
elif [ -f "library.db" ]; then
  warn "Postgres is not running; snapshotting local SQLite fallback library.db."
  mkdir -p "$STAGING/sqlite"
  sqlite3 library.db ".backup '$STAGING/sqlite/library.db'"
  echo "db_backend=sqlite" >> "$STAGING/metadata.txt"
else
  fail "No running Postgres container and no library.db fallback found."
fi

if [ -d "$LIBRARY_ROOT" ]; then
  info "Copying library media from $LIBRARY_ROOT..."
  cp -a "$LIBRARY_ROOT" "$STAGING/library"
else
  warn "Library media root '$LIBRARY_ROOT' does not exist."
fi

mkdir -p "$STAGING/live"
for path in \
  match_data.json match_data.csv control.json status.json recorder.json \
  notes.json notes_audio audio_reviews.json corrections.json review_audio \
  match_stats.json reports
do
  if [ -e "$path" ]; then
    cp -a "$path" "$STAGING/live/"
  fi
done

if [ "${KICKOFF_BACKUP_RECORDINGS:-0}" = "1" ]; then
  for path in recordings match_segments; do
    if [ -e "$path" ]; then
      cp -a "$path" "$STAGING/live/"
    fi
  done
fi

ARCHIVE="$BACKUP_DIR/${NAME}.tar.gz"
tar -czf "$ARCHIVE" -C "$STAGING" .

info "Backup written: $ARCHIVE"
du -sh "$ARCHIVE" 2>/dev/null || true
