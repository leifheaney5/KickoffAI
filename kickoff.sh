#!/usr/bin/env bash
#
# kickoff.sh — Kickoff Pulse's one-button launcher.
#
#   ./kickoff.sh
#
# Sets up a virtualenv (first run only), checks Ollama, starts the audio
# tracker in the background, and launches the Streamlit dashboard. Ctrl+C
# cleanly stops everything.

set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=".venv"
DATA_FILE="${KICKOFF_DATA_FILE:-match_data.json}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2}"

# Match library DB: use the Docker Postgres if it's reachable on :5432,
# otherwise leave KICKOFF_DB_URL unset so db.py falls back to local SQLite.
if [ -z "${KICKOFF_DB_URL:-}" ] && (: < /dev/tcp/localhost/5432) 2>/dev/null; then
  export KICKOFF_DB_URL="postgresql+psycopg://kickoff:kickoff@localhost:5432/kickoff"
fi

green() { printf '\033[0;32m%s\033[0m\n' "$1"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$1"; }
red() { printf '\033[0;31m%s\033[0m\n' "$1"; }

echo "================================================================"
green "  Kickoff Pulse — starting up"
echo "================================================================"

# --------------------------------------------------------------------------- #
# 1. Python virtualenv + dependencies
# --------------------------------------------------------------------------- #
if [ ! -d "$VENV_DIR" ]; then
  yellow "First run: creating virtualenv and installing dependencies..."
  python3 -m venv "$VENV_DIR"
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
else
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
fi
green "✓ Python environment ready ($(python --version 2>&1))"

# --------------------------------------------------------------------------- #
# 2. Check Ollama
# --------------------------------------------------------------------------- #
if curl -fsS "$OLLAMA_URL/api/version" >/dev/null 2>&1; then
  green "✓ Ollama is running at $OLLAMA_URL"
  if ! curl -fsS "$OLLAMA_URL/api/tags" 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
    yellow "⚠ Model '$OLLAMA_MODEL' not found. Pulling it now..."
    ollama pull "$OLLAMA_MODEL" || red "  Could not pull '$OLLAMA_MODEL'. Parsing may fail."
  else
    green "✓ Model '$OLLAMA_MODEL' is available"
  fi
else
  red "⚠ Ollama is NOT reachable at $OLLAMA_URL."
  if command -v ollama >/dev/null 2>&1; then
    yellow "  Attempting to start it (ollama serve)..."
    nohup ollama serve >/tmp/ollama.log 2>&1 &
    sleep 4
    if curl -fsS "$OLLAMA_URL/api/version" >/dev/null 2>&1; then
      green "✓ Ollama is now running"
    else
      red "  Still not reachable. Start it manually: 'ollama serve'"
      yellow "  Continuing anyway — speech will be transcribed but not parsed."
    fi
  else
    red "  Ollama is not installed. Install with: brew install ollama"
    yellow "  Continuing anyway — speech will be transcribed but not parsed."
  fi
fi

# --------------------------------------------------------------------------- #
# 2b. Match library database
# --------------------------------------------------------------------------- #
if [ -n "${KICKOFF_DB_URL:-}" ]; then
  green "✓ Match library using Postgres (docker compose up -d)"
else
  yellow "• Match library using local SQLite (start Postgres with 'docker compose up -d')"
fi

# --------------------------------------------------------------------------- #
# 3. Clean-exit trap
# --------------------------------------------------------------------------- #
AUDIO_PID=""
STREAMLIT_PID=""

cleanup() {
  echo ""
  yellow "Shutting down Kickoff Pulse..."
  [ -n "$STREAMLIT_PID" ] && kill "$STREAMLIT_PID" 2>/dev/null || true
  [ -n "$AUDIO_PID" ] && kill "$AUDIO_PID" 2>/dev/null || true
  # Give them a moment, then force if needed.
  sleep 1
  [ -n "$AUDIO_PID" ] && kill -9 "$AUDIO_PID" 2>/dev/null || true
  green "Done. Match data saved to $DATA_FILE"
  exit 0
}
trap cleanup INT TERM

# --------------------------------------------------------------------------- #
# 4. Start the audio tracker (background)
# --------------------------------------------------------------------------- #
green "Starting the audio tracker (The Ear + The Brain)..."
KICKOFF_DATA_FILE="$DATA_FILE" python audio_tracker.py &
AUDIO_PID=$!
sleep 1

if ! kill -0 "$AUDIO_PID" 2>/dev/null; then
  red "Audio tracker failed to start. Check the output above."
  red "Tip: grant microphone permission to your terminal in"
  red "System Settings > Privacy & Security > Microphone."
  exit 1
fi
green "✓ Audio tracker running (PID $AUDIO_PID)"

# --------------------------------------------------------------------------- #
# 5. Launch the dashboard (opens the browser)
# --------------------------------------------------------------------------- #
green "Launching the dashboard in your browser..."
echo "----------------------------------------------------------------"
yellow "  Speak your play-by-play into the mic."
yellow "  Press Ctrl+C here to stop everything."
echo "----------------------------------------------------------------"

# Streamlit runs in the foreground; Ctrl+C triggers the trap above.
KICKOFF_DATA_FILE="$DATA_FILE" streamlit run dashboard.py \
  --server.headless false --browser.gatherUsageStats false &
STREAMLIT_PID=$!

# Wait on streamlit; if it exits on its own, clean up too.
wait "$STREAMLIT_PID"
cleanup
