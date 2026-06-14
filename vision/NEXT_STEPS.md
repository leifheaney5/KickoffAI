# Next steps — pick up here

A snapshot of where the vision work stands and the **outstanding tasks**, in
priority order, with commands. Start by reading this, then `LOCAL_MODEL_SETUP.md`
(set up + run). Big-picture plan: `ROADMAP.md`. Training detail: `ANNOTATION.md`.

## Where we are (works today)

- **Local model** `soccer_yolov8m_v1.pt` runs fully offline. On the youth "Veo"
  clip: ~19% ball, referees in ~80% of frames, ~4 players/frame — matches the
  Roboflow *cloud* model, but local.
- **GPU training works** (RTX 3080, torch `+cu126`).
- **Live UI**: *Video Analysis* (camera + tactical map + live stats) and
  *Team Shape* (heatmaps, formation, territory) + a local AI analyst that
  answers positioning questions from the computed findings.
- **Everything is in the repo** (code, model, dataset, annotation frames).

## Known limitations (why the work below matters)

- **Ball ~19% on youth footage** — domain gap (model trained on *pro* footage).
  Possession/passing can't fire reliably until this improves.
- **Heatmaps/positions are image-space (uncalibrated)** — perspective squashes
  pitch depth; the auto pitch-detection model finds nothing on the
  football-field markings of this footage.
- **Per-player identity fragments** (~75 track-ids for ~22 players) — no jersey
  numbers yet + the panning camera breaks tracks.

## Outstanding tasks (priority order)

### 1. Annotate your footage + retrain — THE keystone

Fixes the 19% ball ceiling *and* adds jersey numbers (stable identity). The
shipped model never saw your footage.

- Re-extract frames at **1080p** (sharper ball):
  `python -m vision.sample_frames --video <1080p_match.mp4> --out annotation_frames --count 300`
- Upload `annotation_frames/` (or `annotation_frames.zip`) to a Roboflow
  project; use **Label Assist**; label **ball, player, referee, jersey_number**.
- Export YOLOv8, then retrain on the GPU:
  `python -m vision.train --data <data.yaml> --base yolov8x.pt --imgsz 1280 --epochs 100 --device 0 --workers 2`
- Deploy: copy the new `best.pt` over `soccer_yolov8m_v1.pt` (or pass `--model`).
- Full guide: `ANNOTATION.md`.

### 2. Pitch calibration — makes the geometry real (blocked on fixed-camera footage)

Today's heatmaps are image-space. A **fixed (non-panning) camera** + 4 known
pitch points = a correct homography → true pitch positions/distances and the
door to possession.

- Needs a **not-yet-built** manual 4-point calibration step (the auto pitch
  model fails on football-field markings — confirmed: 0 keypoints/frame).
- When you have a fixed-panorama export, ask Claude: *"build a manual 4-point
  pitch calibration in the Video Analysis page and feed it as the homography."*
  The plumbing exists — `PitchHomography.from_correspondences()` already takes
  4+ point pairs; the pipeline accepts a `homography=` / `pitch_detector=`.

### 3. Validate possession & passing on real footage

Never confirmed on real video (ball was too sparse). After #1 (better ball) and
#2 (calibration), run the pipeline and check `match_stats.json` for non-empty
`passing_stats` + a real possession split, then bridge into the dashboard:
`python -m vision.bridge --stats match_stats.json --out match_data.json`.

### 4. Turn on jersey-number identity (after #1 adds the class)

Already scaffolded in `teams.py` / `pipeline.py` (the `JerseyOCR` + binder).
Once the model emits `jersey_number`, per-player heatmaps / distance / minutes
become reliable — no more 75-track fragmentation.

## Minor / polish

- **Video Analysis page runs inference on CPU** (hardcoded `device="cpu"`). On a
  CUDA machine, add a device selector or set `device="0"` for a big speedup.
- **Ollama** must be running for the analyst Q&A: `ollama serve` +
  `ollama pull llama3.2`.
- The current annotation frames are **720p** — re-extract at 1080p (task #1).
- Consider **Git LFS** if the repo keeps gaining large binaries.
