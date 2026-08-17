#!/usr/bin/env bash
#
# Restore a backup created by scripts/backup_now.sh.
#
# Usage:
#   scripts/restore_backup.sh backups/kickoff_backup_YYYYmmdd_HHMMSS.tar.gz --force
#   scripts/restore_backup.sh backup.tar.gz --force --with-live

set -euo pipefail

cd "$(dirname "$0")/.."

LIBRARY_ROOT="${KICKOFF_LIBRARY_ROOT:-library}"
POSTGRES_CONTAINER="${KICKOFF_POSTGRES_CONTAINER:-kickoff-postgres}"
POSTGRES_USER="${KICKOFF_POSTGRES_USER:-kickoff}"
POSTGRES_DB="${KICKOFF_POSTGRES_DB:-kickoff}"
STAMP="$(date +%Y%m%d_%H%M%S)"
FORCE=0
WITH_LIVE=0
ARCHIVE=""

usage() {
  printf '%s\n' \
    "Restore a backup created by scripts/backup_now.sh." \
    "" \
    "Usage:" \
    "  scripts/restore_backup.sh backups/kickoff_backup_YYYYmmdd_HHMMSS.tar.gz --force" \
    "  scripts/restore_backup.sh backup.tar.gz --force --with-live"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --force)
      FORCE=1
      ;;
    --with-live)
      WITH_LIVE=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [ -z "$ARCHIVE" ]; then
        ARCHIVE="$1"
      else
        usage
        exit 2
      fi
      ;;
  esac
  shift
done

[ -n "$ARCHIVE" ] || { usage; exit 2; }
[ -f "$ARCHIVE" ] || { echo "error: backup archive not found: $ARCHIVE" >&2; exit 1; }
[ "$FORCE" = "1" ] || {
  echo "error: restore overwrites database/library state; rerun with --force" >&2
  exit 1
}

WORK="$(mktemp -d "${TMPDIR:-/tmp}/kickoff_restore_${STAMP}.XXXXXX")"
cleanup() {
  rm -rf "$WORK"
}
trap cleanup EXIT

tar -xzf "$ARCHIVE" -C "$WORK"

postgres_running() {
  command -v docker >/dev/null 2>&1 &&
    docker inspect -f '{{.State.Running}}' "$POSTGRES_CONTAINER" 2>/dev/null |
    grep -q '^true$'
}

if [ -f "$WORK/postgres.sql.gz" ]; then
  postgres_running || {
    echo "error: $POSTGRES_CONTAINER is not running; start Docker/Postgres first" >&2
    exit 1
  }
  echo "Restoring Postgres database into $POSTGRES_CONTAINER..."
  gunzip -c "$WORK/postgres.sql.gz" |
    docker exec -i "$POSTGRES_CONTAINER" psql \
      -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"
elif [ -f "$WORK/sqlite/library.db" ]; then
  echo "Restoring SQLite fallback library.db..."
  if [ -e "library.db" ]; then
    mv "library.db" "library.db.restore-pre-${STAMP}"
  fi
  cp -a "$WORK/sqlite/library.db" "library.db"
else
  echo "error: archive does not contain a supported database snapshot" >&2
  exit 1
fi

if [ -d "$WORK/library" ]; then
  echo "Restoring media library to $LIBRARY_ROOT..."
  if [ -e "$LIBRARY_ROOT" ]; then
    mv "$LIBRARY_ROOT" "${LIBRARY_ROOT}.restore-pre-${STAMP}"
  fi
  cp -a "$WORK/library" "$LIBRARY_ROOT"
else
  echo "warning: archive has no library/ media folder" >&2
fi

if [ "$WITH_LIVE" = "1" ] && [ -d "$WORK/live" ]; then
  echo "Restoring live runtime files..."
  for src in "$WORK/live"/*; do
    [ -e "$src" ] || continue
    base="$(basename "$src")"
    if [ -e "$base" ]; then
      mv "$base" "${base}.restore-pre-${STAMP}"
    fi
    cp -a "$src" "$base"
  done
fi

echo "Restore complete."
