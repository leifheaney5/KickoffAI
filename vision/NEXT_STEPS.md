# Next steps — pick up here

A snapshot of where the vision work stands and the **outstanding tasks**, in
priority order, with commands. Start by reading this, then `LOCAL_MODEL_SETUP.md`
(set up + run). Big-picture plan: `ROADMAP.md`. Training detail: `ANNOTATION.md`.

## Where we are (works today)

- **Local model** `soccer_yolov8m_v1.pt` runs fully offline. On the youth "Veo"
  clip: ~19% ball, referees in ~80% of frames, ~4 players/frame — matches the
  Roboflow *cloud* model, but local.
- **GPU training works** (RTX 3080, torch `+cu126`).
- **Live UI**: the Eye runs as a persistent process (`scripts/live_vision.py`),
  started and stopped from the **Match Console**; **Live Eye** shows the frame
  full-size, **Film Room** analyses recorded files, and **Team Shape** gives
  heatmaps / formation / territory, plus a local AI analyst that answers
  positioning questions from the computed findings.
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

### 2. Pitch calibration — BUILT (v1.12.0); needs fixed-camera footage to use

Manual 4-point calibration now lives on the **Camera & Feed** page: grab a frame
from the configured feed, mark four known landmarks, save. The homography
persists and every later run projects through it.

- Still needs a **fixed (non-panning) camera** export to be worth doing — an
  auto-following Veo camera invalidates a static homography.
- Until a run is calibrated, positions stay image-space; `quality.py` says so
  explicitly in the report rather than leaving it implied.

### 3. Validate possession & passing on real footage

Never confirmed on real video (ball was too sparse). After task 1 (better ball)
and task 2 (calibration), run the pipeline and check `match_stats.json` for
non-empty `passing_stats` + a real possession split, then bridge into the
dashboard: `python -m vision.bridge --stats match_stats.json --out match_data.json`.

Since v1.13.0 you no longer have to eyeball this: every run writes a
`run_quality` block and `quality.py` grades it **measured / indicative /
unusable**. The report states the grade, and only *measured* runs feed season
trends. Task 1 is what moves runs from indicative to measured.

### 4. Turn on jersey-number identity (after #1 adds the class)

Already scaffolded in `teams.py` / `pipeline.py` (the `JerseyOCR` + binder).
Once the model emits `jersey_number`, per-player heatmaps / distance / minutes
become reliable — no more 75-track fragmentation.

## Minor / polish

- **Ollama** must be running for the analyst Q&A: `ollama serve` +
  `ollama pull llama3.2`.
- The current annotation frames are **720p** — re-extract at 1080p (task #1).
- Consider **Git LFS** if the repo keeps gaining large binaries.
