# ⚽ KickoffAI

A fully-local, real-time soccer stats tracker for Apple Silicon Macs. Narrate a
match into your mic and watch a live dashboard fill up with stats — no cloud, no
API keys.

```
  🎙  Your voice
      │
      ▼
  audio_tracker.py ── The Ear   (SpeechRecognition + mlx-whisper)
      │  transcript
      ▼
  Ollama (llama3.2) ── The Brain (transcript → strict JSON event)
      │  event
      ▼
  match_data.json  ── The Database
      │
      ▼
  dashboard.py ──── The Display (Streamlit, auto-refresh)
```

## Quick start

```bash
./kickoff.sh
```

On first run this creates a `.venv`, installs dependencies, verifies Ollama and
the `llama3.2` model, starts the audio tracker, and opens the dashboard in your
browser. Press **Ctrl+C** in the terminal to stop everything cleanly.

## What to say

Speak natural play-by-play, one event per breath, e.g.:

- "Home number 10 with a shot on target from the box"
- "Away tackle in midfield, won the ball"
- "Goal for the home team!"
- "Great save by the away keeper"
- "Yellow card for the home number 4" · "Away defender sent off, red card"
- "Corner kick for the home side" · "Offside against the away striker"
- "Foul by the away defender on the left wing"

The brain maps everything to two teams: **Home** and **Away**. Tracked stats:
goals, shots, shots on target, saves, tackles, fouls, yellow/red cards,
corners, offsides, passes & pass accuracy, and an estimated possession share.

## Requirements

- macOS on Apple Silicon (Intel works too via the openai-whisper fallback)
- Python 3.9+
- [Ollama](https://ollama.com) with the `llama3.2` model
  (`brew install --cask ollama-app && ollama pull llama3.2`)
- `ffmpeg` (Whisper uses it to decode audio): `brew install ffmpeg`
- `portaudio` (PyAudio build dependency): `brew install portaudio`
- Microphone permission granted to your terminal app
  (System Settings → Privacy & Security → Microphone)

## Files

| File | Role |
|------|------|
| `audio_tracker.py` | Listens, transcribes, parses via Ollama, writes events |
| `dashboard.py`     | Streamlit real-time dashboard |
| `kickoff.sh`       | One-button launcher with clean shutdown |
| `requirements.txt` | Python dependencies |

## Configuration (optional env vars)

| Variable | Default | Meaning |
|----------|---------|---------|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `llama3.2` | Model used for parsing |
| `WHISPER_MLX_MODEL` | `mlx-community/whisper-base.en-mlx` | mlx-whisper model |
| `WHISPER_MODEL` | `base.en` | openai-whisper fallback model |
| `KICKOFF_DATA_FILE` | `match_data.json` | Where events are stored |

## Troubleshooting

- **No transcription / mic errors:** grant mic permission to your terminal and
  re-run. The tracker prints a clear message if access is denied.
- **Events logged but not parsed:** make sure Ollama is running
  (`brew services start ollama`).
- **Dashboard not live-updating:** ensure `streamlit-autorefresh` installed
  (it's in `requirements.txt`).
