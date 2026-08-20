# Kickoff Pulse — Development Plan

Phases are sequenced by dependency and value. Each phase ships on its own branch
and can be reviewed/merged independently. Vision phases that need the retrained
model are explicitly marked as blocked.

---

## Phase 1 — Stash reconcile (foundation) ✓ DONE

**Branch:** `feature/stash-reconcile` · **Size:** M · No blockers

The local stash from before the latest `git pull` contained ~717 lines of new
work merged with 8 remote commits. Resolving this first gave every later phase
a clean base.

**What shipped:**

- "Thoughts mode" — tracker toggle captures free-form voice notes instead of
  events; clips saved to `notes_audio/`, index in `notes.json`
- Microphone picker (`pick_microphone()`) — pin a specific input device via
  `KICKOFF_MIC`
- `apply_corrections()` — post-transcription fixes for words Whisper mangles
- `is_real_speech()` — rejects noise bursts, hallucinations, low-confidence
  transcripts before sending to Ollama
- Lineup support in `parse_event()` — shirt numbers map to names; side inferred
- `gate_to_threshold()` / live noise-gate slider wired to `control.json`
- Structured lineup editor in the dashboard (formation + roster per team)
- Synopsis recordings UI in Match Insights (playback + delete)

---

## Phase 2 — Audio quality ✓ DONE (included in Phase 1 stash)

**Branch:** N/A — shipped in `feature/stash-reconcile` · **Size:** S

All tasks were already in the stash and reconciled in Phase 1:

- Word-count + repetition + hallucination rejection in `is_real_speech()`
- `no_speech_prob` / `avg_logprob` confidence gates passed through from Whisper
- `adjust_for_ambient_noise()` startup calibration (1 s of silence on launch)
- Live noise-gate slider in the dashboard drives `energy_threshold` each loop

---

## Phase 3 — Event undo ✓ DONE

**Branch:** `feature/event-undo` · **Size:** S · No blockers

**What shipped:**

- `pop_last_event()` in `stats.py` — atomically removes the last entry
- "Undo last event" button below the timer controls, only shown when events exist
- `st.toast` confirms the removed action and team

---

## Phase 4 — Share card integration ✓ DONE

**Branch:** `feature/share-card` · **Size:** S · No blockers

**What shipped:**

- `share_image.py` added to version control (was untracked)
- "Share card" button in the Export panel calls `render_to_bytes()` and serves
  a 1080×1350 portrait PNG via `st.download_button`
- `timeline_image._font` dependency verified present

---

## Phase 5 — Vision: MPS / device auto-detect ✓ DONE

**Branch:** `feature/vision-mps` · **Size:** S · No blockers

**What shipped:**

- `best_device()` probes torch for CUDA → MPS → CPU
- Device selectbox in the Local YOLO controls, defaulting to Auto
- Auto label shows the resolved device name so the user knows what will run
- 80 annotation frames sampled from the 360p YouTube clip into
  `annotation_frames_360p/` as a bootstrap dataset

---

## Phase 6 — Vision: retrain on own footage

**Branch:** `feature/vision-retrain` · **Size:** L · **Blocked on: 1080p match clip**

The current model (`soccer_yolov8m_v1.pt`) was trained on pro broadcast footage;
ball detection on youth footage is ~19%. This is the keystone that unblocks
possession, passing, and stable player identity.

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

**Done when:** `match_stats.json` shows `ball` detections in >50% of frames and
`passing_stats` is non-empty.

---

## Phase 7 — Vision: pitch calibration

**Branch:** `feature/vision-calibration` · **Size:** M · **Blocked on: fixed-camera footage**

Today's heatmaps use image-space coordinates — pitch depth is squashed by
perspective. A manual 4-point calibration step produces a correct homography
and unlocks real-metre distances, formations, and territory.

The auto pitch model finds 0 keypoints on this footage (football-field markings,
not stadium lines) — confirmed. Manual calibration is required.

**Tasks:**

- Add a "Calibration" sub-tab to the Team Shape page with a 4-point click UI
  (click four pitch corners on a reference frame → map to known pitch dimensions)
- Persist the homography to `pitch_cal.json`
- Feed it into the existing `PitchHomography.from_correspondences()` plumbing;
  heatmaps and shape metrics auto-upgrade to real metres
- Add a re-projection validation overlay

**Done when:** Four-corner calibration produces heatmap distances matching a
real pitch (~100 m × 68 m).

---

## Phase 8 — Vision: jersey-number identity

**Branch:** `feature/vision-identity` · **Size:** M · **Blocked on: Phase 6**

Player identity fragments across ~75 track IDs for ~22 players because the
panning camera breaks ByteTrack. Jersey-number OCR anchors each track to a
permanent ID regardless of camera movement.

The scaffolding already exists in `vision/teams.py` (`JerseyOCR`) and
`vision/pipeline.py` — it just needs the `jersey_number` class from Phase 6.

**Tasks:**

- Validate `JerseyOCR` reads numbers from the Phase 6 model's bounding boxes
- Tune binder confidence threshold and de-duplication logic
- Wire per-player stable IDs to Team Shape heatmaps and the player stats table
- Update `vision/bridge.py` to emit player-keyed stats in `match_data.json`

**Done when:** A 5-minute clip produces ≤ 25 unique player IDs and per-player
heatmaps are visually correct.

---

## Dependency map

```text
Phase 1 (stash reconcile) ✓
  └── Phase 2 (audio quality) ✓

Phase 3 (event undo) ✓     ← independent
Phase 4 (share card) ✓     ← independent
Phase 5 (vision MPS) ✓     ← independent

Phase 6 (vision retrain)   ← blocked on 1080p clip
  └── Phase 8 (identity)

Phase 7 (pitch calibration) ← blocked on fixed-camera footage
```

## Current status

Phases 1–5 are complete on their branches, ready to merge. Phases 6–8 are
blocked on external assets (1080p match clip, fixed-camera footage export).

When the Veo clip arrives: run `sample_frames` at 1080p, annotate in Roboflow,
retrain on the GPU desktop, then open Phase 6 branch.
