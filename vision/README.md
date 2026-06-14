# Kickoff Pulse — Vision pipeline (the Eye)

A fully-local computer-vision stack that analyses soccer match video and writes
a structured `match_stats.json` — no cloud, no API keys. It complements the
audio tracker ("the Ear"): the Ear hears play-by-play, the Eye watches the
pitch.

```
video frame
    │
    ▼
detection.py   ── YOLO (player / ball / referee / jersey_number) + BoT-SORT/ByteTrack
    │
    ▼
tracking.py    ── identity permanence (re-claim ids after occlusion / panning)
    │
    ▼
homography.py  ── pixels → pitch (metres for distances, 0..100 for output)
    │
    ▼
teams.py       ── HSV K-Means team split + EasyOCR jersey numbers
    │
    ▼
heuristics.py  ── possession + passing state machine
    │
    ▼
pipeline.py    ── orchestration → match_stats.json
```

## Install

The vision extras are heavy (YOLO/torch/EasyOCR), so they live apart from the
base app:

```bash
pip install -r requirements.txt -r vision/requirements.txt
# Optional CUDA torch for GPU speed (install before the line above):
#   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

## Run

```bash
# Quick demo on a stock COCO model (players + ball only, uncalibrated):
python -m vision --video match.mp4

# Full run: fine-tuned model, four pitch reference points, GPU:
python -m vision --video match.mp4 \
    --model models/soccer_yolov8x.pt --device cuda --tracker botsort \
    --points "120,80;1800,75;1850,1000;90,1010" \
    --output match_stats.json
```

`--points` are four image-pixel landmarks (e.g. the four corner flags, in a
consistent order). `--pitch-points` optionally gives their real positions in
metres; the default assumes the four pitch corners. Without `--points` the
pipeline still runs but emits **uncalibrated** image-space coordinates (relative
positions only — distances are not physically accurate).

### As a library

```python
from vision import PipelineConfig, PitchHomography, MatchAnalyzer

config = PipelineConfig(model_path="models/soccer_yolov8x.pt", device="cuda")
homography = PitchHomography(
    image_points=[(120, 80), (1800, 75), (1850, 1000), (90, 1010)],
)
stats = MatchAnalyzer(config, homography).run("match.mp4")
print(stats.possession.team_home_percentage)
```

## Feed the dashboard (bridge)

[`bridge.py`](bridge.py) maps the pipeline's `match_stats.json` onto the event
schema the live dashboard / timeline already consume — so the Eye feeds the same
UI as the Ear. Each vision pass becomes an `action="pass"` event (rendered with
the Pass badge), carrying outcome, team, shirt number, pass type, pitch zone and
raw coordinates.

```bash
# Idempotent augment: add/refresh vision passes in the dashboard's data file
python -m vision.bridge --stats match_stats.json --out match_data.json

# Or preview safely into a separate file, then point the dashboard at it:
python -m vision.bridge --stats match_stats.json --out match_data.vision.json --fresh
#   KICKOFF_DATA_FILE=match_data.vision.json streamlit run dashboard.py
```

Re-running is idempotent: previously-bridged events (`source: "vision"`) are
replaced, and any audio/manual events are preserved. Possession is reported in
the run summary (the current dashboard has no possession widget yet).

## Train a soccer model

Stock COCO models only provide `person`/`sports ball` and detect the small, fast
ball poorly. For real stats, fine-tune a model on soccer footage — datasets at
<https://universe.roboflow.com/browse/sports/soccer>. [`train.py`](train.py)
downloads a Roboflow dataset and trains YOLO (needs a CUDA **GPU**):

```bash
python -m vision.train --api-key $ROBOFLOW_API_KEY \
    --workspace roboflow-jvuqo --project football-players-detection-3zvbc \
    --version 12 --base yolov8x.pt --epochs 100 --imgsz 1280 --device 0
# then:
python -m vision --video match.mp4 --model runs/soccer/kickoff_pulse/weights/best.pt
```

That dataset's classes (`ball`, `goalkeeper`, `player`, `referee`) fold into the
pipeline automatically (`goalkeeper` → `player` via the class aliases). Jersey
numbers are a separate dataset/head.

## Validation / demo results

- **Core logic** (homography, identity re-ID, possession + passing, schema) is
  covered by a dependency-light smoke test — passes cleanly.
- **Full pipeline** was run end-to-end on a real 1080p clip on **CPU** with a
  stock model: detection, BoT-SORT tracking, identity permanence, team K-Means,
  homography and JSON output all functioned (~2.4 fps with `yolov8n` @ 640px).
- With a stock COCO model the ball was detected in only ~2/80 frames, so the
  ball-dependent possession/passing heuristics stay quiet — exactly the gap a
  soccer-trained model closes (see **Train a soccer model**). The heuristics
  themselves are validated separately by the smoke test.

## Notes on the heuristics

- **Possession**: the nearest player within `possession_radius_m` (1.5 m) for
  `possession_frames` (15) consecutive *sampled* frames is the confirmed holder;
  each confirmed frame is tallied toward the possession share.
- **Passes**: a `controlled → in_flight → received` state machine logs completed
  passes (same team), interceptions (opponent), and incomplete passes (out of
  play or never controlled), typed ground / lofted / through from trajectory,
  speed, mid-flight detection gaps and the space around the receiver.
- A **soccer-fine-tuned** model is recommended. A stock `yolov8x.pt` runs (its
  `person`/`sports ball` classes are aliased to `player`/`ball`) but cannot
  produce `referee` or `jersey_number` detections, so team OCR is unavailable.

Every threshold lives in [`config.py`](config.py) (`PipelineConfig`) and can be
overridden in code, on the CLI, or via `KICKOFF_VISION_*` environment variables.
