---
name: analyze-video
description: Run the Kickoff Pulse computer-vision pipeline (the Eye) on match footage to produce match_stats (possession, passing, player/ball positioning). Use when asked to analyze, process, or run CV/vision on a match video, Veo clip, or recording.
---

# Analyze match footage with CV

Runs YOLO detection + tracking + team split + possession/passing heuristics over
a video file, writing a vision `match_stats` JSON. Tuned for the **uncalibrated,
auto-following Veo camera** this project records (pans/zooms, no calibration), so
results are directional, not metric.

## Pick the right path first

| Situation | Use |
|---|---|
| A match happening **now** | The app: **Camera & Feed** → test the feed → **Match Console** → Start. The Eye runs as a persistent process and survives navigation. No terminal needed. |
| A recorded file, interactively | The app: **Film Room** — pick the file, Run analysis, review the tactical + passing maps. |
| A recorded file, batch/tuned | This skill's CLI steps below — best for long runs, custom flags, or scripted work. |

The CLI and the app share `vision/runtime.py` and `vision/render.py`, so a run
started either way is configured and drawn the same.

## Prerequisites (check first)

- Vision deps in `.venv` (`ultralytics`, `torch`, `cv2`) and the fine-tuned
  model `soccer_yolov8m_v1.pt` in the repo root. `torch.backends.mps.is_available()`
  should be True on Apple Silicon.
- **The possession tuning flags must exist on the current branch.** Check:
  `grep -c possession-radius vision/__main__.py` — if `0`, they live only on the
  `vision-uncalibrated-tuning` branch. Merge that branch to main (or
  `git switch vision-uncalibrated-tuning`) before running, or the
  `--possession-radius` / `--possession-frames` flags will error.

## Step 1 — Inspect the source (HLS `.ts` captures are often corrupt)

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,duration -of csv=p=0 FILE
ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of default=nw=1 FILE
```

If `nb_read_frames / fps` is far short of `duration`, the stream is truncated by a
decode error. Try an error-resilient transcode (note: a badly broken bitstream
may not recover much — re-check decodable frames after):

```bash
ffmpeg -y -err_detect ignore_err -fflags +genpts+discardcorrupt -i FILE \
  -c:v libx264 -preset veryfast -crf 20 -an repaired.mp4
```

## Step 2 — Validate on a 90s slice before the full run

```bash
.venv/bin/python -m vision --video FILE --model soccer_yolov8m_v1.pt --device mps \
  --stride 3 --imgsz 1280 --conf 0.25 --no-ocr --max-seconds 90 \
  --possession-radius 15 --possession-frames 4 --output match_stats_validate.json
```

Confirm players are detected, ball-detection % is healthy, and **possession is
non-zero with passes > 0**. If possession is 0/0, lower `--possession-frames`
(try 3) — the default 15 never survives this camera's track-id churn.

## Step 3 — Full run (background; ~real-time on MPS)

Drop `--max-seconds`, pick an output name, run detached and report when done:

```bash
.venv/bin/python -m vision --video FILE --model soccer_yolov8m_v1.pt --device mps \
  --stride 3 --imgsz 1280 --conf 0.25 --no-ocr \
  --possession-radius 15 --possession-frames 4 --output match_stats_<slug>.json
```

## Notes

- Uncalibrated image-space coordinates (0..100): possession %, pass counts and
  positions are **relative/directional**, not real metres. True metric coords
  would need a per-frame pitch homography (`--pitch-model`, needs a Roboflow key).
- OCR is off for speed (players are track tokens, not jersey numbers). Enable by
  dropping `--no-ocr` if numbered players are needed (much slower).
- Optional: bridge passes into the dashboard log with `python -m vision.bridge
  --stats match_stats_<slug>.json --out match_data.json` (idempotent; preserves
  audio events). For 2nd-half-only footage the clock starts at the video's 0:00,
  so it is **not** time-aligned to the audio log — keep CV separate unless offset.
- This CV layer is intentionally **not** embedded in the coach report
  (see `generate-report`).
