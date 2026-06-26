---
name: launch-app
description: Start the full Kickoff Pulse stack (Ollama + audio tracker + Streamlit/desktop) and verify it is serving. Use when asked to start, launch, run, or boot the app / dashboard / Kickoff Pulse.
---

# Launch Kickoff Pulse

`kickoff.sh` is the launcher. It ensures the `.venv`, starts Ollama if needed,
then brings up the UI.

## Run it

From the repo root, in the background (it stays running):

```bash
./kickoff.sh
```

- **Default (`KICKOFF_UI=desktop`)** launches `desktop.py`, which spawns the
  audio tracker + Streamlit (headless on 127.0.0.1:8501) inside a native window.
- **Browser-only:** `KICKOFF_UI=web ./kickoff.sh` runs the audio tracker plus
  Streamlit; open http://127.0.0.1:8501.
- **Microphone:** select a mic with `KICKOFF_MIC="AirPods" ./kickoff.sh`.

## Requirements

- **Postgres** for live use (the match library): `docker compose up -d` brings up
  Postgres on localhost:5432. For dev-only SQLite, set `KICKOFF_ALLOW_SQLITE=1`.
- **Ollama** must be installed; `kickoff.sh` starts `ollama serve` if it is not
  already reachable (logs to `/tmp/ollama.log`).
- Per-machine env (e.g. `KICKOFF_MIC`) can live in `.env` — Finder/Dock launches
  read it there, not from the shell profile.

## Verify it came up

```bash
curl -s -m 5 -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8501/healthz
```

A `200` means the server is healthy. If the **desktop window is grey / "unable
to connect" but healthz returns 200**, the webview's socket went stale — just
open http://127.0.0.1:8501 in a browser (`open http://127.0.0.1:8501`). Do **not**
restart the stack mid-match; that would also kill the audio tracker. See
`app-doctor` for deeper triage.
