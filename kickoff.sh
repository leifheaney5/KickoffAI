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
EMBED_MODEL="${KICKOFF_EMBED_MODEL:-nomic-embed-text}"
KICKOFF_UI="${KICKOFF_UI:-desktop}"

# Match library DB: live launches should use Postgres. SQLite is still useful
# for development, but it must be explicit so match-day data cannot split across
# backends by accident.
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
  # Embedding model powers the library's semantic search (optional).
  if [ -n "${KICKOFF_DB_URL:-}" ] && \
     ! curl -fsS "$OLLAMA_URL/api/tags" 2>/dev/null | grep -q "$EMBED_MODEL"; then
    yellow "⚠ Embedding model '$EMBED_MODEL' not found. Pulling for semantic search…"
    ollama pull "$EMBED_MODEL" || yellow "  Skipped — semantic search will be disabled."
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
elif [ "${KICKOFF_ALLOW_SQLITE:-0}" = "1" ]; then
  yellow "• Match library using local SQLite (explicit KICKOFF_ALLOW_SQLITE=1)"
else
  red "✗ Match library Postgres is not reachable on localhost:5432."
  red "  Start it with: docker compose up -d"
  yellow "  For dev-only SQLite, run: KICKOFF_ALLOW_SQLITE=1 ./kickoff.sh"
  exit 1
fi

# --------------------------------------------------------------------------- #
# 2c. Ingest mode — vision is the primary path; voice is the backup lane.
#
# The mic tracker is a real cost (a always-on microphone, CPU, and a model
# round-trip per phrase), so it only starts when this match actually uses it.
# Set it on the Camera & Feed page, or override here with KICKOFF_INGEST.
# --------------------------------------------------------------------------- #
INGEST_MODE="${KICKOFF_INGEST:-$(python - <<'PY' 2>/dev/null || echo vision
import control
print(control.load_control().get("ingest_mode", "vision"))
PY
)}"

case "$INGEST_MODE" in
  vision) green "✓ Ingest: vision only (the Eye)" ;;
  both)   green "✓ Ingest: vision + voice notes" ;;
  voice)  yellow "• Ingest: voice only — the Eye is off for this match" ;;
  *)      yellow "• Unknown ingest mode '$INGEST_MODE'; using vision"
          INGEST_MODE="vision" ;;
esac

if [ "$INGEST_MODE" = "vision" ] || [ "$INGEST_MODE" = "both" ]; then
  if [ ! -f "soccer_yolov8m_v1.pt" ] && [ ! -f "yolov8m.pt" ]; then
    yellow "⚠ No YOLO weights found in the repo. The Eye will try to download"
    yellow "  stock weights on first start; soccer-trained weights work better."
  fi
  if ! python -c "import cv2" >/dev/null 2>&1; then
    red "✗ Vision dependencies are missing — the Eye cannot start."
    yellow "  Install them with: pip install -r vision/requirements.txt"
  fi
fi

# --------------------------------------------------------------------------- #
# 3. Clean-exit trap
# --------------------------------------------------------------------------- #
if [ "$KICKOFF_UI" != "browser" ]; then
  green "Launching the native desktop app..."
  echo "----------------------------------------------------------------"
  if [ "$INGEST_MODE" = "voice" ]; then
    yellow "  Speak your play-by-play into the mic."
  else
    yellow "  Open Match Console and press Start to run the Eye on your feed."
  fi
  yellow "  Close the app window or press Ctrl+C here to stop everything."
  echo "----------------------------------------------------------------"
  KICKOFF_INGEST="$INGEST_MODE" KICKOFF_DATA_FILE="$DATA_FILE" python desktop.py
  exit $?
fi

AUDIO_PID=""
STREAMLIT_PID=""

cleanup() {
  echo ""
  yellow "Shutting down Kickoff Pulse..."
  [ -n "$STREAMLIT_PID" ] && kill "$STREAMLIT_PID" 2>/dev/null || true
  [ -n "$AUDIO_PID" ] && kill "$AUDIO_PID" 2>/dev/null || true
  # The Eye is a detached process so it survives page navigation; shutting the
  # whole app down is the one time we do want it to stop. It checkpoints on the
  # way out, so accumulated possession/passing is preserved.
  python -c "import vision_runner; vision_runner.stop()" >/dev/null 2>&1 || true
  # Give them a moment, then force if needed.
  sleep 1
  [ -n "$AUDIO_PID" ] && kill -9 "$AUDIO_PID" 2>/dev/null || true
  green "Done. Match data saved to $DATA_FILE"
  exit 0
}
trap cleanup INT TERM

# --------------------------------------------------------------------------- #
# 4. Start the audio tracker (background) — only when this match uses voice
# --------------------------------------------------------------------------- #
if [ "$INGEST_MODE" = "vision" ]; then
  green "• Audio tracker not started (vision-only match)."
  yellow "  Need it? Switch ingest mode on Camera & Feed, or: KICKOFF_INGEST=both ./kickoff.sh"
else
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
fi

# --------------------------------------------------------------------------- #
# 5. Launch the dashboard in browser mode
# --------------------------------------------------------------------------- #
green "Launching the dashboard in browser mode..."
echo "----------------------------------------------------------------"
if [ "$INGEST_MODE" = "voice" ]; then
  yellow "  Speak your play-by-play into the mic."
else
  yellow "  Open Match Console and press Start to run the Eye on your feed."
fi
yellow "  Press Ctrl+C here to stop everything."
echo "----------------------------------------------------------------"

# --------------------------------------------------------------------------- #
# Optional: serve the sideline view to phones on the same wifi.
#
# Off by default. Binding beyond localhost is a deliberate choice, so say plainly
# what it exposes and print the code needed to view it.
# --------------------------------------------------------------------------- #
BIND_ADDR="127.0.0.1"
if [ "${KICKOFF_LAN:-0}" = "1" ]; then
  BIND_ADDR="0.0.0.0"
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
  if [ -z "${KICKOFF_SIDELINE_CODE:-}" ]; then
    KICKOFF_SIDELINE_CODE="$(python -c 'import secrets;print(f"{secrets.randbelow(10**6):06d}")')"
    export KICKOFF_SIDELINE_CODE
  fi
  echo "----------------------------------------------------------------"
  yellow "  LAN mode: this app is reachable by anyone on your network."
  green  "  Sideline view:  http://${LAN_IP:-<this-machine>}:8501"
  green  "  Access code:    $KICKOFF_SIDELINE_CODE"
  echo "----------------------------------------------------------------"
fi

# Streamlit runs in the foreground; Ctrl+C triggers the trap above.
KICKOFF_DATA_FILE="$DATA_FILE" streamlit run dashboard.py \
  --server.address "$BIND_ADDR" \
  --server.headless false --browser.gatherUsageStats false &
STREAMLIT_PID=$!

# Wait on streamlit; if it exits on its own, clean up too.
wait "$STREAMLIT_PID"
cleanup
