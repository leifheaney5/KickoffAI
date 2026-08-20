# Match Library — setup

The match library indexes every match and its artifacts in a database. Postgres
is the intended backend for live use (via Docker). Without it, the lower-level
Python modules can still fall back to a local SQLite file for development, but
the normal app launcher requires Postgres unless you explicitly opt into SQLite.

## Before anything: Python 3.13

Every command below assumes a Python 3.13 virtualenv. 3.13 is a floor, not a
preference — older interpreters install everything "successfully" and then hand
you silently older packages (see the README's *Why Python 3.13*). `psycopg` and
`SQLAlchemy` both need current builds to have working 3.13 wheels.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

Check an existing environment at any time with `python depcheck.py`.

## Quick start (SQLite, no Docker)

Nothing to install beyond the Python deps. The library uses `library.db` in the
repo root automatically.

```bash
pip install -r requirements.txt
python -c "import db; db.init_db()"      # creates the schema
KICKOFF_ALLOW_SQLITE=1 ./kickoff.sh      # dev-only launcher fallback
```

## Postgres via Docker (recommended)

1. Install Docker Desktop (macOS) or Docker Engine (Linux).
2. Start the stack:

   ```bash
   docker compose up -d                  # postgres + metabase + backups
   docker compose --profile tools up -d  # + pgAdmin at http://localhost:5050
   ```

3. Point the app at it and create the schema:

   ```bash
   export KICKOFF_DB_URL="postgresql+psycopg://kickoff:kickoff@localhost:5432/kickoff"
   python -c "import db; db.init_db()"
   ```

   `kickoff.sh` auto-detects the Postgres container and sets this for you. If it
   cannot reach Postgres, it exits instead of silently using SQLite; add the
   `export` to your shell profile if you run the app some other way.

### Services & ports

| Service   | URL / port              | What it's for                          |
|-----------|-------------------------|----------------------------------------|
| postgres  | `localhost:5432`        | Match library DB (pgvector-enabled)    |
| metabase  | <http://localhost:3000> | Analytics dashboards over the data     |
| backup    | (writes to a volume)    | Scheduled `pg_dump` with retention     |
| pgadmin   | <http://localhost:5050> | DB inspector (`tools` profile)         |

### Analytics (Metabase)

Open <http://localhost:3000>, create the admin account on first run, then add
the kickoff database as a data source: host `postgres`, port `5432`, database
`kickoff`, user/password `kickoff`. Metabase keeps its own metadata in a
separate volume, so it never touches the match schema. From there it auto-builds
charts over `matches` / `events` / `media_files` — cross-match trends, player
season totals, possession over time, etc.

The in-app **Season** page already covers the headline cross-match views (league
table, top scorers, goals per match). For deeper ad-hoc analysis in Metabase,
paste these into a native SQL question:

```sql
-- Top scorers (real team names)
SELECT e.player,
       CASE e.team WHEN 'Home' THEN m.home_team
                   WHEN 'Away' THEN m.away_team END AS team,
       COUNT(*) AS goals
FROM events e JOIN matches m ON m.id = e.match_id
WHERE (e.action = 'goal' OR e.result = 'scored') AND e.player IS NOT NULL
GROUP BY 1, 2 ORDER BY goals DESC;

-- Goals per match over time
SELECT played_on, name, home_score + away_score AS goals
FROM matches ORDER BY played_on;

-- Matches per competition
SELECT COALESCE(NULLIF(competition, ''), '(none)') AS competition, COUNT(*)
FROM matches GROUP BY 1 ORDER BY 2 DESC;
```

### Backups

The `backup` service runs `pg_dump` on a schedule (`@daily`, 14-day / 4-week /
6-month retention) into the `kickoff_backups` volume. Run one on demand:

```bash
docker exec kickoff-backup /backup.sh
docker exec kickoff-backup ls -lh /backups/last
```

For a portable full backup that you can copy off-machine, use the repo script
instead. It includes the Postgres dump, the `library/` media folder, and active
runtime files such as notes and current match data:

```bash
scripts/backup_now.sh
KICKOFF_BACKUP_DIR=/Volumes/USB/KickoffBackups scripts/backup_now.sh
```

Restore is intentionally guarded:

```bash
scripts/restore_backup.sh backups/kickoff_backup_YYYYmmdd_HHMMSS.tar.gz --force
scripts/restore_backup.sh backups/kickoff_backup_YYYYmmdd_HHMMSS.tar.gz --force --with-live
```

If Postgres reports a collation-version warning after an image upgrade, run a
fresh backup and refresh the database metadata:

```bash
scripts/backup_now.sh
scripts/refresh_postgres_collation.sh --force
```

### Semantic search (pgvector + Ollama)

The Match Library page has an **AI search** toggle that ranks matches by meaning,
not just text. It needs the Postgres backend (pgvector) and a local embedding
model:

```bash
ollama pull nomic-embed-text
```

Matches are embedded automatically when finalized or imported; semantic search
degrades to plain text filtering if the model or Postgres isn't available.

### pgAdmin (optional DB browser)

With the `tools` profile running, open <http://localhost:5050>
(login `admin@kickoff.example.com` / `kickoff`) and add a server pointing at host
`postgres`, port `5432`, user/password `kickoff`.

## LLM (Ollama) — keep it native on macOS

The app's AI features (event parsing, match summaries, the analyst Q&A) use a
local LLM at `OLLAMA_URL` (default `http://localhost:11434`).

- **macOS / Apple Silicon:** run Ollama **natively** — it uses the Metal GPU and
  is noticeably faster than a container.

  ```bash
  brew install ollama && ollama serve
  ollama pull llama3.2
  ```

- **Reproducible / Linux with NVIDIA:** use the bundled container instead:

  ```bash
  docker compose --profile llm up -d
  docker exec kickoff-ollama ollama pull llama3.2
  ```

Either way the app config is identical — it just talks to `localhost:11434`.

## What stays native (not containerized)

- **Whisper transcription** — `mlx-whisper` is Apple-Silicon-only and needs live
  microphone access.
- **Vision / YOLO** — MPS acceleration isn't available to Mac containers, so
  native inference is faster.
- **Streamlit app + audio tracker** — need mic access; they talk to Postgres and
  Ollama over `localhost`.

## Resetting

```bash
docker compose down            # stop services (keeps data)
docker compose down -v         # stop AND wipe the Postgres/Ollama volumes
```
