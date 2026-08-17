# UI & Ingest Streamlining Plan — vision-first, voice as backup

Target version: **1.12.0** (minor — user-facing restructure, no data-format break).

The app was built audio-first and the UI still says so: the mic console is the
default page, the vision runner cannot be started from the app at all, and
"the Eye" is split across two pages in two different nav groups. This plan
inverts that — **visual ingest becomes the primary path, voice becomes an
explicit backup lane** — and reshapes the sidebar around the match lifecycle.

---

## Where we are today

| Symptom | Evidence |
|---|---|
| Audio is the default experience | [dashboard.py:31](dashboard.py#L31) sets `Live_Match.py` (the mic console) as `default=True`; [kickoff.sh:139](kickoff.sh#L139) unconditionally starts `audio_tracker.py` and prints "Speak your play-by-play into the mic" |
| Vision cannot be started from the UI | [pages/9_Live_Eye.py:63-68](pages/9_Live_Eye.py#L63-L68) tells the user to open a terminal and paste a `scripts/live_vision.py` command |
| Vision is split across two nav groups | "Live Eye" under **Live**, "Video Analysis" under **Analysis** — the second is the one that actually configures the pipeline |
| Two divergent live-vision code paths | [pages/4_Video_Analysis.py:851-938](pages/4_Video_Analysis.py#L851-L938) runs a stepping loop that dies on navigation; [scripts/live_vision.py](scripts/live_vision.py) runs durably. `build_config` and `annotate` are duplicated between them |
| The feed source is not persisted anywhere | Stream URL lives in `st.session_state["kp_va_stream_url"]`; `live_vision.py` takes it as `--video` on the CLI; `control.json` has no source field ([control.py:69-101](control.py#L69-L101)) |
| Calibration is buried | Pitch homography — essential for a fixed Veo camera — sits in a collapsed expander at [pages/4_Video_Analysis.py:629](pages/4_Video_Analysis.py#L629), inside a 965-line page |
| Status chips are audio-only | [ui_helpers.py:269-315](ui_helpers.py#L269-L315) shows mic state, "Heard", event count — nothing about the Eye |
| Sidebar is 13 entries over 4 groups | Manual Entry (a fallback) sits at the same level as Timeline; nothing signals which ingest path is live |

Two things already work in our favour and the plan leans on both:

- `live_vision.py` already writes `.live_vision.pid`, honours a `.live_eye_paused`
  flag file, and checkpoints to `match_stats.json` + `match_data.json`. It is a
  well-behaved daemon that simply has no UI.
- [screen_recorder.py](screen_recorder.py) is a proven pattern for supervising a
  long-running subprocess from Streamlit: `is_supported() / status() / start() /
  stop()` over a `recorder.json` state file with PID liveness checks. The vision
  supervisor should mirror that API exactly.

---

## Phase 0 — Foundation: persisted feed config + a vision supervisor

Nothing else can be built until the app can start and describe a vision run.
This phase ships no new pages.

**0a. Add ingest state to `control.json`** — [control.py](control.py)

Extend `DEFAULT` with:

```python
"ingest_mode": "vision",          # "vision" | "voice" | "both"
"feed": {
    "kind": "stream",             # "stream" | "webcam" | "file"
    "url": "",                    # HLS .m3u8 (Veo) or YouTube fallback
    "camera_index": 0,
    "file_path": "",
    "model": "soccer_yolov8m_v1.pt",
    "device": "auto",             # resolved via best_device()
    "stride": 6,
    "imgsz": 960,
    "conf": 0.25,
},
```

`load_control()` already deep-merges defaults, so old `control.json` files pick
these up with no migration. Add `control.feed_source(state)` returning the
resolved source (URL, int index, or path) so every caller agrees.

**0b. New module `vision_runner.py`** — mirrors `screen_recorder`'s API

```python
def is_supported() -> bool          # venv python + model weights present
def status() -> dict                # {running, pid, elapsed, source, log, error}
def start(state) -> dict            # spawn scripts/live_vision.py from control.feed
def stop(timeout=8.0) -> dict       # SIGTERM, wait for final checkpoint
def pause() / resume() -> dict      # touch/remove .live_eye_paused
def log_tail(n=40) -> str           # last lines of recordings/live_vision.log
```

State file `vision_runner.json` (alongside `recorder.json`), PID liveness via
`os.kill(pid, 0)`. `start()` builds the argv from `control.feed` — the same
flags `live_vision.py` already accepts, so **no changes to the runner itself**
beyond one addition: write a small `live_eye_status.json` each checkpoint with
`{fps, frames, ball_detect_rate, passes, possession, last_frame_at}` so the UI
has real health numbers instead of re-parsing the 4 MB `match_stats.json`.

**0c. Health signal for the Eye** — `vision_runner.health(status)` returns
`ok | stale | starting | down` using `last_frame_at` age, the same way
`control.tracker_online(status, max_age=8.0)` does for audio.

Done when: `vision_runner.start()` from a Python REPL launches the Eye, and
`status()` reports running with a rising frame count; `stop()` leaves a final
checkpoint and no orphan process.

Tests: `tests/test_vision_runner.py` — argv construction from a `control` dict,
state round-trip, stale-PID reconciliation (reuse the `app-doctor` skill's
existing orphan logic as the reference).

---

## Phase 1 — Sidebar restructure

Rewrite the `st.navigation` map in [dashboard.py](dashboard.py). Groups follow
the match lifecycle; **vision leads every group it appears in**.

```
Set up
  Match Setup        Match identity, teams, lineups
  Camera & Feed      NEW - source, model, device, calibration, test frame
  Voice Backup       renamed from "Audio & Mic"

Live
  Match Console      DEFAULT - scoreboard, clock, Eye panel, event feed
  Live Eye           full-bleed annotated frame + vision stats

Analysis
  Timeline           Manual Entry folds in as a tab
  Insights
  Team Shape
  Film Room          renamed from "Video Analysis" - recorded files only

After match
  Post-Match
  Match Library
  Season
  Analyst
```

Changes from today:

- **Set up moves above Live.** You configure the feed before kickoff; putting it
  first matches the order you actually touch things.
- **"Audio & Mic" becomes "Voice Backup"** — the name does the teaching.
- **Manual Entry folds into Timeline as a tab** (13 entries down to 11). It is a
  fallback input method, not a destination.
- **"Video Analysis" becomes "Film Room"** and loses its live paths (Phase 5).
- Icons: `videocam` for Camera & Feed, `mic` stays on Voice Backup,
  `visibility` stays on Live Eye.

Page files rename accordingly (`pages/Audio_and_Mic.py` -> `pages/Voice_Backup.py`,
`pages/4_Video_Analysis.py` -> `pages/Film_Room.py`, `pages/9_Live_Eye.py` ->
`pages/Live_Eye.py`). Drop the numeric prefixes from the migrated files — they
are vestigial now that `st.navigation` owns the ordering, and the mixed
numbered/named convention is itself a source of confusion.

Done when: the sidebar reads in lifecycle order, Match Console is default, and
every page still loads (smoke-run each route).

---

## Phase 2 — Camera & Feed page (the new front door for ingest)

New `pages/Camera_and_Feed.py`. This is where Phase 0's config becomes visible.
It absorbs the source/model/calibration blocks that are currently marooned in
Film Room ([pages/4_Video_Analysis.py:397-558](pages/4_Video_Analysis.py#L397-L558)
and the calibration expander at line 629).

Sections, top to bottom:

1. **Feed source** — segmented control: `Veo live stream` / `Webcam` / `Video
   file`. Stream is first and preselected; the placeholder is an `.m3u8` URL,
   with YouTube named as the 360p fallback it is. Writes straight to
   `control.feed`.
2. **Test connection** — grabs one frame via `vision.sources.resolve_video_source`
   and shows it with resolution/fps. This is the single highest-value addition:
   today you discover a bad URL only after the runner fails in a terminal.
3. **Model & device** — weights path, device selector (reuse `best_device()`),
   stride/imgsz/conf. Collapsed under "Advanced" with sane defaults visible as
   a one-line summary.
4. **Pitch calibration** — promoted out of its expander to a first-class section,
   with the grabbed frame and landmark marking. Show a clear
   `Calibrated / Uncalibrated` badge; uncalibrated means image-space coordinates
   and degraded possession accuracy, and the page should say so.
5. **Voice backup toggle** — one switch setting `ingest_mode`, with a plain-language
   caption: "Vision only" / "Vision + voice notes" / "Voice only (no camera)".

Done when: a user can go from a cold app to a verified feed and a calibrated
pitch without touching a terminal or the Film Room page.

---

## Phase 3 — Match Console rebuilt vision-first

Rewrite [pages/Live_Match.py](pages/Live_Match.py) as `pages/Match_Console.py`.
Today it is entirely a mic console; it becomes an ingest-agnostic console whose
primary panel is the Eye.

Layout:

- Hero: match title + scoreboard (unchanged — `UI.render_match_title`,
  `UI.render_scoreboard`).
- **Status chips become ingest-aware.** Refactor
  [ui_helpers.py:269](ui_helpers.py#L269) into `render_status_chips()` that
  composes two chip groups and shows only what is active:
  - Vision: `Eye` (running/stale/down), `FPS`, `Ball` (detection rate),
    `Possession H/A`, `Passes`
  - Voice: the existing `Rec`, `Events`, `Heard` chips
- **Eye panel** — the live annotated frame (`recordings/live_eye.jpg`) at
  moderate size with **Start Eye / Pause / Stop** wired to `vision_runner`.
  This is the change that removes the terminal from the workflow. Start is
  disabled with an inline reason when no feed is configured, linking to
  Camera & Feed.
- **One transport, both ingests.** `Start` on the match clock starts the Eye
  (and the voice tracker only when `ingest_mode` includes voice), matching the
  existing auto-start-recording behaviour at
  [pages/Live_Match.py:42-47](pages/Live_Match.py#L42-L47). `Half` sets the
  pause flag so the runner idles without losing stats — the mechanism
  `live_vision.py` already implements at
  [scripts/live_vision.py:190-202](scripts/live_vision.py#L190-L202).
- Voice sections (Record thoughts, voice guide, Undo) render **only when
  `ingest_mode` includes voice**, and sit below the fold.

`Live_Eye.py` stays as the full-bleed view for when you want the frame large,
and loses its "run this in a terminal" warning in favour of the same
start/stop controls.

Done when: start-to-stats on a live Veo feed is: Camera & Feed -> test -> Match
Console -> Start. No terminal, no page-switch mid-match.

---

## Phase 4 — Voice demoted to a real backup lane

- **`kickoff.sh`**: only start `audio_tracker.py` when `ingest_mode` includes
  voice (read `control.json` with a small `python -c`, defaulting to vision).
  Replace the "Speak your play-by-play into the mic" banner with a mode-aware
  line. Keep `KICKOFF_INGEST=voice` as an env override for a mic-only match.
  Same treatment in [kickoff.ps1](kickoff.ps1) and [desktop.py](desktop.py).
- **`pages/Voice_Backup.py`**: keep every existing control (noise gate, chunking,
  mic calibration, screen capture) and add a short header explaining when to
  reach for voice — no camera, a feed that dropped, or colour commentary the
  Eye cannot see.
- Voice remains fully functional. This phase changes defaults and framing, not
  capability.

Done when: a default `./kickoff.sh` starts the Eye path with no mic process
running, and flipping the toggle brings the tracker back.

---

## Phase 5 — Film Room slimmed

[pages/4_Video_Analysis.py](pages/4_Video_Analysis.py) is 965 lines doing four
jobs. Split it:

- **Extract `vision/render.py`** — `annotate`, `tactical_map`, `passing_map`,
  `_draw_*` helpers (lines 76-338). Both the page and `scripts/live_vision.py`
  import it, deleting the duplicated `annotate` at
  [scripts/live_vision.py:48-64](scripts/live_vision.py#L48-L64).
- **Extract `vision/config_ui.py`** — `build_config()` from `control.feed`, so
  the page, `live_vision.py` (`build_config` at
  [scripts/live_vision.py:85-99](scripts/live_vision.py#L85-L99)) and the
  supervisor all construct pipelines identically.
- **Remove the live paths from the page** (lines 851-948). Live vision is the
  runner's job now; keeping a second, fragile stepping loop is the main source
  of "why did my analysis stop when I clicked away". Film Room handles recorded
  files only: pick a file, run, review tactical + passing maps.
- Source/model/calibration controls move to Camera & Feed (Phase 2); Film Room
  keeps a compact file picker.

Expected result: roughly 965 -> ~350 lines in the page, with the shared drawing
and config code reused by the runner.

Done when: `tests/` pass, a recorded-file run still produces `match_stats.json`,
and the Live Eye frame is drawn by the same code as the Film Room preview.

---

## Phase 6 — Launcher, skills, docs

- **`launch-app` skill** and `kickoff.sh` verify vision readiness (weights
  present, feed configured, `ffmpeg`/`yt-dlp` available) alongside the existing
  Ollama and Postgres checks.
- **`app-doctor` skill** learns `vision_runner.json` — reconcile stale Eye PIDs
  the same way it reconciles `recorder.json` ffmpeg orphans.
- **`analyze-video` skill** points at Film Room for files and the Match Console
  for live, replacing any terminal-first instructions.
- **README + LIBRARY_SETUP** updated to lead with the vision quickstart; the mic
  quickstart moves under a "Voice backup" heading.
- **CHANGELOG.md** entry and version roll to **1.12.0** in `CHANGELOG.md`,
  `build_app.sh` (both `CFBundleShortVersionString` and `CFBundleVersion`), and
  `vision/__init__.py:55`.

---

## Sequencing and risk

| Phase | Depends on | Risk | Mitigation |
|---|---|---|---|
| 0 Foundation | — | Low. Additive; no UI change | New tests; old `control.json` merges cleanly |
| 1 Sidebar | 0 | Low, but page renames touch imports | Grep for `pages/` string references before renaming |
| 2 Camera & Feed | 0 | Medium. Calibration move is fiddly | Port the calibration block verbatim first, restyle second |
| 3 Match Console | 0, 2 | Medium. Transport now drives two subsystems | Keep `vision_runner` failures non-fatal — the clock must never be blocked by a bad feed |
| 4 Voice demotion | 0, 3 | Medium. Changes launcher defaults | `KICKOFF_INGEST=voice` escape hatch; voice capability untouched |
| 5 Film Room | 1 | Medium-high. Largest refactor | Extract modules with tests before deleting the live loop |
| 6 Docs/skills | all | Low | — |

Phases 0-3 are the ones that deliver the stated goal; 4-6 consolidate. If the
work needs to ship in two passes, cut after Phase 3 and release 1.12.0 there.

**Suggested branch:** `feature/vision-first-ui`, with one commit per phase and a
version roll per the project's changelog policy.

## Open questions

1. **Does the Eye survive an app restart?** The runner is a detached process, so
   it should — but the console needs to re-adopt a running PID on load. Assumed
   yes, handled in `vision_runner.status()`.
2. **Half-time behaviour when both ingests are live** — should `Half` pause the
   mic tracker too, or only the Eye? Plan assumes both, since neither should
   log during the interval.
3. **Uncalibrated feeds** — currently allowed with degraded accuracy. Should
   Camera & Feed hard-block Start, or warn? Plan assumes warn, matching the
   existing uncalibrated-possession tuning flags from commit `554a58a`.
