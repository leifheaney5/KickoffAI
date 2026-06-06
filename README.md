# KickoffAI

A fully-local, real-time soccer stats tracker for Apple Silicon Macs. Narrate a
match into your mic and watch a live dashboard fill up with stats — no cloud, no
API keys.

```
  Your voice
      |
      v
  audio_tracker.py --- The Ear   (SpeechRecognition + mlx-whisper)
      |  transcript
      v
  Ollama (llama3.2) --- The Brain (transcript -> strict JSON event)
      |  event
      v
  match_data.json  --- The Database
      |
      v
  dashboard.py ------- The Display (Streamlit, live match clock)
      |
      v
  report.py --------- The Report  (email-friendly .txt + .pdf)
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
- "Yellow card for the home number 4" / "Away defender sent off, red card"
- "Corner kick for the home side" / "Offside against the away striker"
- "Substitution for home, number 9 comes on"
- "Foul by the away defender on the left wing"

The brain maps everything to two teams: **Home** and **Away**, and tracks the
player you name (e.g. "number 6" is tracked as `#6`). Tracked stats: goals,
shots, shots on target, saves, tackles, fouls, yellow/red cards, corners,
offsides, passes & pass accuracy, substitutions, and an estimated possession
share — aggregated per team **and** per player.

## Dashboard features

- **90-minute match clock** with Start / Pause / Halftime / Reset. After 45:00
  (or 90:00 in the second half) it shows **added time** as `+M:SS`. Every logged
  event is stamped with the match-clock reading.
- **Pause recording** — temporarily stop logging events without stopping the app.
- **Per-player stats** table plus a **spotlight card** for any player you pick.
- **Substitutions** list.
- **Post-match summary** — type your own notes, or click **Draft with AI** to
  have the local model write one from the stats.
- **Save & export report** — writes an email-friendly `.txt` and a clean `.pdf`
  into `reports/`, archives the raw data, and offers both as downloads.

## Requirements

- macOS on Apple Silicon (Intel works too via the openai-whisper fallback)
- Python 3.9+
- [Ollama](https://ollama.com) with the `llama3.2` model
  (`brew install --cask ollama-app && ollama pull llama3.2`)
- `ffmpeg` (Whisper uses it to decode audio): `brew install ffmpeg`
- `portaudio` (PyAudio build dependency): `brew install portaudio`
- Microphone permission granted to your terminal app
  (System Settings -> Privacy & Security -> Microphone)

## Files

| File | Role |
|------|------|
| `audio_tracker.py` | Listens, transcribes, parses via Ollama, writes events |
| `dashboard.py`     | Streamlit real-time dashboard (clock, stats, controls) |
| `stats.py`         | Shared stat engine (team + player aggregation) |
| `control.py`       | Shared state: pause flag, match timer, summary notes |
| `report.py`        | Compiles the data into `.txt` + `.pdf` reports |
| `kickoff.sh`       | One-button launcher with clean shutdown |
| `requirements.txt` | Python dependencies |

You can also generate a report from the command line at any time:

```bash
python report.py    # writes reports/match_report_<timestamp>.{txt,pdf}
```

## Configuration (optional env vars)

| Variable | Default | Meaning |
|----------|---------|---------|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `llama3.2` | Model used for parsing |
| `WHISPER_MLX_MODEL` | `mlx-community/whisper-base.en-mlx` | mlx-whisper model |
| `WHISPER_MODEL` | `base.en` | openai-whisper fallback model |
| `KICKOFF_DATA_FILE` | `match_data.json` | Where events are stored |
| `KICKOFF_CONTROL_FILE` | `control.json` | Pause/timer/summary state |
| `KICKOFF_REPORTS_DIR` | `reports` | Where exported reports are written |

## Troubleshooting

- **No transcription / mic errors:** grant mic permission to your terminal and
  re-run. The tracker prints a clear message if access is denied.
- **Events logged but not parsed:** make sure Ollama is running
  (`ollama serve`, or launch the Ollama app).
- **Dashboard not live-updating:** Streamlit 1.37+ uses native fragments; on
  older versions install `streamlit-autorefresh` (it's in `requirements.txt`).
