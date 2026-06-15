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
2. Start Postgres:

   ```bash
   docker compose up -d                  # postgres only
   docker compose --profile tools up -d  # + pgAdmin at http://localhost:5050
   ```

3. Point the app at it and create the schema:

   ```bash
   export KICKOFF_DB_URL="postgresql+psycopg://kickoff:kickoff@localhost:5432/kickoff"
   python -c "import db; db.init_db()"
   ```

   Add that `export` to your shell profile (or `kickoff.sh`) so every process —
   the dashboard, tracker, and library page — uses the same database.

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
