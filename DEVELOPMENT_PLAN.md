# Kickoff Pulse — Development Plan

Phases are sequenced by dependency and value. Each phase ships on its own branch
and can be reviewed/merged independently. Vision phases that need the retrained
model are explicitly marked as blocked.

---

## Phase 1 — Stash reconcile (foundation)
**Branch:** `feature/stash-reconcile`
**Size:** M · No blockers

The local stash from before the latest `git pull` contains ~717 lines of new
work that must be merged with the remote changes before anything else builds
on top of it. Doing this first gives every later phase a clean base.

**What's in the stash:**
- "Thoughts mode" — while the tracker is running, a toggle switches from event
  logging to free-form voice notes; clips saved to `notes_audio/`, index in
  `notes.json`
- Microphone picker (`pick_microphone()`) — lets you select the input device
  at startup instead of always using the default
- `apply_corrections()` — post-transcription word fixes for things Whisper
  reliably mangles (e.g. soccer vocab)
- `is_real_speech()` — filters out noise bursts before sending to Ollama
- Lineup support in `parse_event()` — player name hints improve event parsing
- `gate_to_threshold()` / live energy slider wired to env var

**Files touched:** `audio_tracker.py`, `control.py`, `dashboard.py`, `brand.py`,
`.gitignore`

**Done when:** `git stash pop` resolves cleanly, app runs, thoughts mode
captures a note end-to-end.

---

## Phase 2 — Audio quality
**Branch:** `feature/audio-quality`
**Size:** S · Depends on Phase 1

Reduce false triggers and improve transcript quality beyond what the stash
already adds.

**Tasks:**
- Reject transcripts shorter than a configurable word count (default: 2) before
  sending to Ollama — eliminates single-word noise hits
- Whisper segment confidence gate: skip transcription results below a confidence
  threshold (Whisper returns per-segment `no_speech_prob`; gate on this)
- Startup background-noise calibration: sample 1–2 s of silence on launch and
  set the energy threshold automatically, then let the dashboard slider fine-tune

**Files touched:** `audio_tracker.py`, `control.py`, dashboard threshold UI

**Done when:** Running the tracker in a quiet room produces zero false events
over a 5-minute idle period.

---

## Phase 3 — Event undo
**Branch:** `feature/event-undo`
**Size:** S · No blockers (can run in parallel with Phase 2)

Right now correcting a misheard event requires navigating to Manual Entry and
deleting from a table. A fast undo in the main scoreboard view removes friction
during a live match.

**Tasks:**
- Add "Undo last event" button to the live scoreboard (main dashboard page),
  visible only when at least one event exists
- Wire it to a new `control.pop_last_event()` helper that removes the most
  recent entry from `match_data.json` and rewrites the file
- Show a brief confirmation toast after undo

**Files touched:** `dashboard.py`, `control.py`

**Done when:** Logging a test event then hitting Undo removes it from the feed
and the score updates correctly.

---

## Phase 4 — Share card integration
**Branch:** `feature/share-card`
**Size:** S · No blockers (can run in parallel with Phase 2–3)

`share_image.py` is already written and renders a 1080×1350 portrait summary
card (scoreline, possession bar, headline stats) but it is not wired into the
dashboard — it is an untracked file with no UI entry point.

**Tasks:**
- Move `share_image.py` into version control (already done locally, just needs
  committing on this branch)
- Add a "Share card" button to the post-match export section of `dashboard.py`
  (alongside the existing .txt / .pdf export buttons) that calls
  `share_image.render_to_bytes()` and serves it as `st.download_button`
- Verify `timeline_image._font` dependency is present (it is)

**Files touched:** `share_image.py` (tracked for first time), `dashboard.py`

**Done when:** Clicking "Share card" downloads a valid PNG with the correct
score and stats.

---

## Phase 5 — Vision: MPS / device auto-detect
**Branch:** `feature/vision-mps`
**Size:** S · No blockers

`pages/4_Video_Analysis.py:168` hardcodes `device="cpu"`. On Apple Silicon,
PyTorch MPS gives a meaningful inference speedup.

**Tasks:**
- Replace the hardcoded `"cpu"` with a `best_device()` helper:
  CUDA → MPS → CPU, in that priority order
- Expose a device override in the UI sidebar (a selectbox defaulting to auto)
- Apply the same helper to the CLI path in `vision/__main__.py` (currently
  passes `device` from `--device` arg; add `"auto"` as a valid value)

**Files touched:** `pages/4_Video_Analysis.py`, `vision/__main__.py`,
possibly a new `vision/device.py` utility

**Done when:** Running Video Analysis on this MacBook shows `device=mps` in
the Ultralytics log and inference is measurably faster than CPU.

---

## Phase 6 — Vision: retrain on own footage
**Branch:** `feature/vision-retrain`
**Size:** L · **Blocked on: match clip from Veo/manual source**

The current model (`soccer_yolov8m_v1.pt`) was trained on pro broadcast
footage; ball detection on youth footage is ~19%. This is the keystone that
unblocks possession, passing, and stable player identity.

**Tasks:**
1. Re-extract annotation frames at 1080p from the match clip:
   `python -m vision.sample_frames --video <clip.mp4> --out annotation_frames --count 300`
2. Upload `annotation_frames/` to Roboflow; use Label Assist; label
   `ball`, `player`, `referee`, `jersey_number`
3. Export YOLOv8 dataset and retrain on the GPU desktop:
   `python -m vision.train --data data.yaml --base yolov8x.pt --imgsz 1280 --epochs 100 --device 0 --workers 2`
4. Copy `best.pt` to repo root as `soccer_yolov8m_v2.pt`; update default model
   path in `pages/4_Video_Analysis.py` and `vision/__main__.py`
5. Run the pipeline on a 2-minute clip and confirm ball detection > 50%

**Files touched:** `vision/sample_frames.py`, `pages/4_Video_Analysis.py`,
`vision/__main__.py`, new model binary

**Done when:** `match_stats.json` shows `ball` detections in >50% of frames on
youth footage and `passing_stats` is non-empty.

---

## Phase 7 — Vision: pitch calibration
**Branch:** `feature/vision-calibration`
**Size:** M · **Blocked on: fixed-camera (non-panning) footage export**

Today's heatmaps use image-space coordinates — pitch depth is squashed by
perspective. A manual 4-point calibration step produces a correct homography
and unlocks real-metre distances, formations, and territory.

The auto pitch model (`--pitch-model`) finds 0 keypoints on this footage
(football-field markings, not stadium lines) — confirmed. Manual calibration
is required.

**Tasks:**
- Add a "Calibration" sub-tab to the Team Shape page with a 4-point drag UI
  (click four pitch corners on a reference frame → map to known pitch dimensions)
- Persist the homography to `pitch_cal.json`
- Feed it into the existing `PitchHomography.from_correspondences()` plumbing
  in the pipeline; heatmaps and shape metrics auto-upgrade to real metres
- Add a re-projection validation overlay so the calibration can be verified
  visually

**Files touched:** `pages/5_Team_Shape.py`, `vision/pipeline.py`, new
`pitch_cal.json` schema, `vision/homography.py`

**Done when:** Clicking four pitch corners calibrates the view; the Team Shape
heatmap shows distances in metres that match a real pitch (~100 m × 68 m).

---

## Phase 8 — Vision: jersey-number identity
**Branch:** `feature/vision-identity`
**Size:** M · **Blocked on: Phase 6 (model must emit `jersey_number` class)**

Player identity currently fragments across ~75 track IDs for ~22 players
because the panning camera breaks ByteTrack. Jersey-number OCR can anchor each
track to a permanent ID regardless of camera movement.

The scaffolding already exists in `vision/teams.py` (`JerseyOCR`) and
`vision/pipeline.py` (the binder) — it just has no data to work with until
Phase 6 adds the `jersey_number` detection class.

**Tasks:**
- Validate that `JerseyOCR` correctly reads numbers from the Phase 6 model's
  `jersey_number` bounding boxes on real footage
- Tune the binder's confidence threshold and de-duplication logic
- Wire per-player stable IDs through to Team Shape heatmaps and the
  per-player stats table in the dashboard
- Update `vision/bridge.py` to emit player-keyed stats in `match_data.json`

**Files touched:** `vision/teams.py`, `vision/pipeline.py`, `vision/bridge.py`,
`pages/5_Team_Shape.py`, `dashboard.py`

**Done when:** A 5-minute clip produces ≤ 25 unique player IDs (one per player)
and per-player heatmaps are visually correct.

---

## Dependency map

```
Phase 1 (stash reconcile)
  └── Phase 2 (audio quality)

Phase 3 (event undo)          ← independent, ship anytime
Phase 4 (share card)          ← independent, ship anytime
Phase 5 (vision MPS)          ← independent, ship anytime

Phase 6 (vision retrain)      ← blocked on match clip
  └── Phase 8 (identity)

Phase 7 (pitch calibration)   ← blocked on fixed-camera footage
```

## Immediate next actions

1. `git stash pop` and resolve conflicts → open Phase 1 branch
2. While Phase 1 is in review: open Phase 3, 4, and 5 in parallel (all
   independent)
3. When the Veo clip arrives → start Phase 6 annotation on the GPU desktop
