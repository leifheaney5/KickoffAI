# Phase 6 — Vision Retrain Plan (the keystone)

Train a soccer detection model on **your own footage** so the vision pipeline
works on youth/Veo video, not just pro broadcast. This is the single highest-
impact vision task: it lifts ball detection from ~19% and adds the
`jersey_number` class that unlocks stable player identity (Phase 8) and
ball-dependent stats — possession, passing (Phase 5 of the vision roadmap).

**Status:** blocked on one input — a **1080p match clip** exported from Veo (or
downloaded at 1080p). Everything else is ready.

---

## Why this is the keystone

- The shipped model (`soccer_yolov8m_v1.pt`) learned from the public
  *football-players* broadcast dataset. On the youth Veo footage it finds the
  ball in only ~19% of frames — too sparse for possession/passing to fire.
- No `jersey_number` class exists, so player tracks fragment (~75 track-ids for
  ~22 players) and per-player stats are unreliable.
- Fixing the domain gap + adding jersey numbers is what makes the on-pitch
  analytics trustworthy. Reports, library, and season analytics are already
  built and waiting for richer vision data to flow in.

## What we already have

- `annotation_frames.zip` — 300 frames sampled across a full match (in-repo).
- `annotation_frames_360p/` — 80 frames sampled from the current 360p clip
  (bootstrap only; re-extract at 1080p for real training).
- GPU training path proven on the RTX 3080 (torch `+cu126`).
- `vision/train.py`, `vision/sample_frames.py`, `vision/bridge.py` in place.
- The MPS/CUDA device auto-detect already shipped (Phase 5).

## The one blocker

A **1080p** match clip. The YouTube source only serves 360p via yt-dlp
(SABR-restricted); 360p is too soft for the small ball. Export a 1080p clip from
Veo directly, or obtain a 1080p download, and drop it in the repo.

---

## Workflow

### Step 1 — Extract frames at 1080p

```bash
python -m vision.sample_frames --video <1080p_match.mp4> \
    --out annotation_frames --count 300
```

Sample across both halves and both ends of the pitch so the model sees varied
lighting, scale, and crowding.

### Step 2 — Annotate in Roboflow

1. New Object Detection project at roboflow.com.
2. Upload `annotation_frames/` (or the zip).
3. Turn on **Label Assist** with `football-players-detection-3zvbc` to
   pre-suggest boxes; correct them.
4. Label four classes: **`ball`, `player`, `referee`, `jersey_number`**
   (`goalkeeper` folds into `player` via the pipeline aliases).
   - Box every visible shirt number — this is what gives each player a permanent
     identity.
5. Generate a dataset **Version** (export **YOLOv8**). Add brightness/blur
   augmentations to help the small ball.

### Step 3 — Train on the GPU desktop

```bash
# From a Roboflow version:
python -m vision.train --api-key $ROBOFLOW_API_KEY \
    --workspace <ws> --project <proj> --version <n> \
    --base yolov8x.pt --imgsz 1280 --epochs 100 --device 0 --workers 2

# Or from an exported local data.yaml:
python -m vision.train --data path/to/data.yaml \
    --base yolov8x.pt --imgsz 1280 --epochs 100 --device 0 --workers 2
```

- Combine your frames with the public `football-players` set for volume.
- ⚠ Keep `--workers` low (2–4) on Windows/limited RAM (8 caused CPU-RAM OOM at
  1280px).
- ⚠ Run via the module (`python -m vision.train …`), never a heredoc — Windows
  multiprocessing dataloaders re-import `<stdin>` and crash.
- Output: `runs/.../weights/best.pt`. Also train a faster laptop variant with
  `--base yolov8s.pt` and optionally `yolo export model=best.pt format=onnx`.

### Step 4 — Deploy

```bash
cp runs/.../weights/best.pt soccer_yolov8m_v2.pt
```

Update the default model path in `pages/4_Video_Analysis.py` and
`vision/__main__.py` to `soccer_yolov8m_v2.pt` (or pass `--model`).

### Step 5 — Validate + bridge into the app

```bash
python -m vision --video clip.mp4 --model soccer_yolov8m_v2.pt --imgsz 1280 \
    --output match_stats.json
python -m vision.bridge --stats match_stats.json --out match_data.json
```

Check `match_stats.json`: ball detected in **>50%** of frames and `passing_stats`
non-empty. Then the existing finalize/library/analytics flow carries it forward —
including the vision stats now bundled into each archived match.

---

## Acceptance criteria

- Ball detected in **>50%** of frames on youth footage (up from ~19%).
- Model emits a `jersey_number` class with usable boxes.
- `match_stats.json` has a real possession split + non-empty `passing_stats`.
- New model committed (or documented) and wired as the default.

## Unlocks next

- **Vision Phase 7 — pitch calibration:** manual 4-point homography → real-metre
  heatmaps/distances (needs fixed-camera footage).
- **Vision Phase 8 — jersey identity:** `JerseyOCR` binding (already scaffolded
  in `vision/teams.py`) → stable per-player stats once `jersey_number` lands.
- **Vision Phase 5 — ball-dependent analytics:** possession, passing network,
  territory pressure feeding the dashboard + season analytics.

## Risks

| Risk | Mitigation |
|---|---|
| Ball still weak after retrain | more 1080p frames, heavier aug, `yolov8x` @ 1280, raise epochs |
| Jersey OCR noisy | tune binder confidence + dedupe (Phase 8) |
| Panning camera breaks tracks | jersey-number anchoring (Phase 8); team-level stats first |
| GPU VRAM limits | drop to `yolov8m` @ 1280; match `--batch` to VRAM |
