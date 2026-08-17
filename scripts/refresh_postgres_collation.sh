#!/usr/bin/env bash
#
# Refresh Postgres collation metadata after backing up the database.
#
# Usage:
#   scripts/backup_now.sh
#   scripts/refresh_postgres_collation.sh --force

set -euo pipefail

cd "$(dirname "$0")/.."

POSTGRES_CONTAINER="${KICKOFF_POSTGRES_CONTAINER:-kickoff-postgres}"
POSTGRES_USER="${KICKOFF_POSTGRES_USER:-kickoff}"
POSTGRES_DB="${KICKOFF_POSTGRES_DB:-kickoff}"

if [ "${1:-}" != "--force" ]; then
  echo "error: run a fresh backup first, then rerun with --force" >&2
  exit 1
fi

if ! docker inspect -f '{{.State.Running}}' "$POSTGRES_CONTAINER" 2>/dev/null |
  grep -q '^true$'; then
  echo "error: $POSTGRES_CONTAINER is not running" >&2
  exit 1
fi

docker exec "$POSTGRES_CONTAINER" psql -v ON_ERROR_STOP=1 \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "REINDEX DATABASE ${POSTGRES_DB};" \
  -c "ALTER DATABASE ${POSTGRES_DB} REFRESH COLLATION VERSION;"
