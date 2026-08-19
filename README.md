# Kickoff Pulse

<p align="center">
  <img src="branding/kickoff-pulse-logo-white-bg.png" alt="Kickoff Pulse" width="360">
</p>

**Kickoff Pulse** is an AI-powered soccer intelligence platform — the pulse of
the match. A fully-local, real-time soccer stats tracker (Apple Silicon Macs and
Windows). Point it at your camera feed and watch a live dashboard fill up with
stats — no cloud, no API keys.

It has two ways to capture a match. **Vision is the primary path**; voice is the
backup for when there is no camera, or for the calls a camera cannot make.

```
  Camera feed (Veo HLS / webcam)        Your voice  [backup]
      |                                     |
      v                                     v
  scripts/live_vision.py -- The Eye     audio_tracker.py -- The Ear
      |  detections, possession, passes      |  transcript
      |                                     v
      |                                 Ollama (llama3.2) -- The Brain
      |                                     |  event
      v                                     v
  match_stats.json  ------------------>  match_data.json  -- The Database
                                            |
                                            v
                                        dashboard.py ----- The Display
                                            |
                                            v
                                        report.py -------- The Report
```

## Quick start

macOS / Linux:

```bash
./kickoff.sh
```

Windows (PowerShell 7+):

```powershell
.\kickoff.ps1
```

On first run this creates a `.venv`, installs dependencies, verifies Ollama and
the `llama3.2` model, and opens the dashboard in the native desktop window. Press
**Ctrl+C** in the terminal, or close the app window, to stop everything cleanly.

For browser-tab debugging, run:

```bash
KICKOFF_UI=browser ./kickoff.sh
```

### Running a match with vision (the default)

1. **Camera & Feed** — paste your Veo `.m3u8` stream URL (or pick a webcam) and
   press **Test connection** to confirm a frame arrives.
2. Still there, calibrate the pitch once for a fixed camera. Uncalibrated feeds
   still work, but positions stay in image space and possession is approximate.
3. **Match Console** — press **Start**. The clock and the Eye start together.
   The Eye runs as its own process, so it keeps analysing wherever you navigate.
4. At the break, press **Half** — the Eye idles and keeps every accumulated stat,
   then re-opens from the live edge when you resume.

### Using voice as well, or instead

Switch **Ingest mode** on Camera & Feed:

| Mode | What runs |
|---|---|
| Vision only *(default)* | The Eye. No microphone is opened. |
| Vision + voice notes | The Eye, plus the mic for fouls, cards, subs and your own notes. |
| Voice only | The mic-driven tracker, as the app worked before. No camera needed. |

Override for a single launch with `KICKOFF_INGEST=both ./kickoff.sh`.

### Starting the next match

The working files describe exactly one match. When you're done, **Post-Match →
Save match to library**, then **Start new match** — that clears the event log,
notes and camera stats and mints a fresh match id, keeping your team names,
lineups and camera feed. It warns before discarding anything unarchived.

## Sideline view (watch from the touchline)

A coach during a match is on the touchline, not at a laptop. Launch with
`KICKOFF_LAN=1 ./kickoff.sh` and the app also serves to your local network; the
launcher prints the URL and an access code. Open it on a phone and the
**Sideline** page shows the scoreboard, the Eye's latest frame and recent events.

It is **read-only** — nothing on it can write, so a phone can never disturb a
live capture. Access is gated: with club accounts in use you sign in as normal;
without them, LAN mode requires the printed code. Binding to the network is
opt-in, and "anyone on the wifi can watch" should be a decision rather than a
surprise.

## Club mode (several coaches, one library)

Optional, and off until you turn it on. With no accounts, Kickoff Pulse behaves
exactly as a single-coach app and never asks you to sign in.

1. **Account → Create administrator account.** This enables sign-in for everyone
   using the install and makes you the admin.
2. Add coaches and teams under **Account** (admin only). Matches are stamped with
   whoever captured them; the library and season are scoped to what you can see.
3. To share a library, run Postgres on a club machine and point each laptop at
   it with `KICKOFF_SHARED_DB_URL`.

Capture never depends on the server. Matches archive to the laptop first and push
when there's a connection — **Account → Club sync**. A pitch with no signal is
the normal case, not an error.

> **Security scope.** Sign-in is intended for a self-hosted club server on a
> trusted network. It is *not* hardened for exposure to the open internet — that
> needs TLS, rate limiting and a security review. If you bind Postgres beyond
> localhost (`KICKOFF_PG_BIND`), you **must** set `KICKOFF_PG_PASSWORD`; the
> default credentials are only safe because the port is localhost-only.

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

- **Status chips** at the top, showing only the ingest paths this match uses.
  For vision: the Eye's health (pulsing when analysing, amber while starting or
  paused, red when it stops responding), **fps**, **ball-detection rate**, live
  possession and pass count. For voice: the glowing mic, **recording time**,
  **session time**, event count, and the last phrase heard.
- **The Eye panel** — the latest annotated frame with Start / Pause / Stop. The
  runner is its own process, so it keeps analysing wherever you navigate and
  closing the page does not stop it.
- **90-minute match clock** with Start / Pause / Halftime / Reset. Start begins
  the clock and every configured ingest together; Halftime idles the Eye without
  losing accumulated stats. After 45:00 (or 90:00 in the second half) it shows
  **added time** as `+M:SS`. Every logged event is stamped with the match clock.
- **Pause mic** — temporarily stop logging voice events without stopping the app.
- **Match notes** — type an observation and it is stamped with the match clock,
  listed newest-first, and carried into the post-match report and the library
  archive. Always available, whatever the ingest mode; when voice is on you can
  speak notes instead from a second tab. Each note is tagged written or voice.
- **Per-player stats** table plus a **spotlight card** for any player you pick.
- **Substitutions** list.
- **Post-match summary** — type your own notes, or click **Draft with AI** to
  have the local model write one from the stats.
- **Save & export report** — writes an email-friendly `.txt` and a clean `.pdf`
  into `reports/`, archives the raw data, and offers both as downloads.

### Timeline page

A second page (in the sidebar) shows a **visual vertical timeline**: a coloured
icon badge for every event (goal, card, sub, save, shot, ...) with a
team-coloured ring. Click any event to expand its full details, filter by event
type, flip the order, and **export the timeline as a PNG**. The same image is
embedded into the exported PDF report.

### Insights page

A third page turns the event log into analysis:

- A **momentum graph** — a decaying, weighted read on who is pressing and when
  the game swung (above the line = Home, below = Away).
- **Headline numbers** — shots, shots on target, conversion, and the current
  momentum leader.
- An **AI analyst** you can ask anything about the match ("Who's on top?",
  "What should the trailing team change?") — answered **locally** by the Ollama
  model from the live data, with quick one-tap prompts and a chat box.

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
| `scripts/live_vision.py` | The Eye: persistent live CV runner (detections, possession, passes) |
| `vision_runner.py` | Supervises the Eye from the app (start/pause/stop, health) |
| `vision/runtime.py` | Shared device selection + pipeline config for every caller |
| `vision/render.py` | Shared drawing: annotated frames, tactical map, passing map |
| `audio_tracker.py` | Listens, transcribes, parses via Ollama, writes events |
| `dashboard.py`     | App entry point + grouped navigation |
| `pages/Camera_and_Feed.py` | Feed source, connection test, model, pitch calibration |
| `pages/Match_Console.py` | Live hub: scoreboard, transport, the Eye, event feed |
| `pages/Live_Eye.py` | Full-size view of the vision runner |
| `pages/Film_Room.py` | Recorded-file analysis + tactical/passing maps |
| `pages/Timeline.py` | Visual, clickable timeline page + image export |
| `pages/Insights.py` | Momentum graph + local AI match analyst |
| `insights.py`      | Momentum engine + AI analyst context builder |
| `brand.py`         | Brand kit: palette, fonts, logo assets, design-system CSS |
| `stats.py`         | Shared stat engine (team + player aggregation) |
| `control.py`       | Shared state: pause flag, match timer, summary notes |
| `icons.py`         | Shared event categories, colours, and SVG icon badges |
| `timeline_image.py`| Renders the timeline PNG (for export + PDF embed) |
| `report.py`        | Compiles the data into `.txt` + `.pdf` reports |
| `quality.py`       | Trust gate: grades each camera run measured/indicative/unusable |
| `auth.py`          | Club sign-in: password hashing, sessions, visibility scoping |
| `sync.py`          | Offline-tolerant push of local matches to the club library |
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
| `WHISPER_MLX_MODEL` | `mlx-community/whisper-medium.en-mlx` | mlx-whisper model |
| `WHISPER_MODEL` | `medium.en` | openai-whisper fallback model |
| `KICKOFF_INITIAL_PROMPT` | built-in soccer prompt | Optional Whisper vocabulary prompt |
| `KICKOFF_DATA_FILE` | `match_data.json` | Where events are stored |
| `KICKOFF_CONTROL_FILE` | `control.json` | Pause/timer/summary state |
| `KICKOFF_AUDIO_REVIEWS_FILE` | `audio_reviews.json` | Audio review sidecar |
| `KICKOFF_REVIEW_AUDIO_DIR` | `review_audio` | Saved review WAV clips |
| `KICKOFF_CORRECTIONS_FILE` | `corrections.json` | Learned voice corrections |
| `KICKOFF_PHRASE_TIME_LIMIT` | `10` | Max seconds per captured phrase |
| `KICKOFF_POST_SPEECH_PADDING` | `0.15` | Non-speaking audio kept around phrases |
| `KICKOFF_REPORTS_DIR` | `reports` | Where exported reports are written |
| `KICKOFF_RECORD_DIR` | `recordings` | Where screen recordings are saved |
| `KICKOFF_RECORDER_FILE` | `recorder.json` | Screen recorder runtime state |
| `KICKOFF_VISION_STATE_FILE` | `vision_runner.json` | Vision runner (the Eye) runtime state |
| `KICKOFF_RECORDINGS_KEEP_DAYS` | `30` | Delete recordings older than this (0 = never) |
| `KICKOFF_RECORDINGS_MAX_GB` | `20` | Cap the recordings directory, oldest first (0 = no cap) |
| `KICKOFF_SHARED_DB_URL` | unset | Club server Postgres; unset = local library only |
| `KICKOFF_SHARED_LIBRARY_ROOT` | unset | Where club artifacts (reports, stats) are copied |
| `KICKOFF_SYNC_VIDEO` | `0` | Include match video in a club sync (large) |
| `KICKOFF_SYNC_MEDIA_MAX_MB` | `512` | Skip any single artifact larger than this |
| `KICKOFF_LAN` | `0` | Serve to the local network so phones can open the Sideline view |
| `KICKOFF_SIDELINE_CODE` | generated | Access code for the Sideline view in LAN mode |
| `KICKOFF_SESSION_FILE` | `~/.kickoff_session.json` | Where this machine remembers a sign-in |
| `KICKOFF_PG_PASSWORD` | `kickoff` | Postgres password — **must** be set if you bind beyond localhost |
| `KICKOFF_PG_BIND` | `127.0.0.1` | Postgres bind address; `0.0.0.0` serves a club LAN |
| `KICKOFF_INGEST` | from `control.json` | Override ingest mode: `vision`, `both`, or `voice` |
| `KICKOFF_MIC` | system default | Mic index or name substring for narration + screen capture audio |

## Audio ingest review

The tracker saves reviewable audio clips and transcript metadata in
`audio_reviews.json` / `review_audio/`. Pending events on the Timeline page show
a “Did you mean…” prompt; approving or editing one can add a local learned
correction to `corrections.json`.

Generate a starter benchmark manifest:

```bash
python audio_benchmark.py --print-starter
```

## Troubleshooting

- **No transcription / mic errors:** grant mic permission to your terminal and
  re-run. The tracker prints a clear message if access is denied.
- **Soccer terms misheard:** the default is `medium.en` for better match
  narration accuracy. If live tracking feels delayed, override it with
  `WHISPER_MODEL=small.en` or the matching `WHISPER_MLX_MODEL` on Apple Silicon.
  The tracker also applies a soccer correction layer before parsing, including
  common Home/Away, action, and spoken-shirt-number fixes.
- **Events logged but not parsed:** make sure Ollama is running
  (`ollama serve`, or launch the Ollama app).
- **Dashboard not live-updating:** Streamlit 1.37+ uses native fragments; on
  older versions install `streamlit-autorefresh` (it's in `requirements.txt`).
- **Screen recording will not start:** install `ffmpeg` (`brew install ffmpeg`)
  and grant Screen Recording permission to the terminal/Python app that launches
  Kickoff Pulse, then restart `./kickoff.sh`.
