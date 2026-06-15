# Match Library — setup

The match library indexes every match and its artifacts in a database. Postgres
is the intended backend (via Docker); without it the app falls back to a local
SQLite file, so you can run everything with zero setup while developing.

## Quick start (SQLite, no Docker)

Nothing to install beyond the Python deps. The library uses `library.db` in the
repo root automatically.

```bash
pip install -r requirements.txt
python -c "import db; db.init_db()"      # creates the schema
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

   `kickoff.sh` auto-detects the Postgres container and sets this for you; add
   the `export` to your shell profile if you run the app some other way.

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

### Backups

The `backup` service runs `pg_dump` on a schedule (`@daily`, 14-day / 4-week /
6-month retention) into the `kickoff_backups` volume. Run one on demand:

```bash
docker exec kickoff-backup /backup.sh
docker exec kickoff-backup ls -lh /backups/last
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
