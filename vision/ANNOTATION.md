# Train a soccer model on your footage — turnkey steps

This is the keystone that unblocks ball detection + jersey numbers (→ stable
identity → reliable per-player stats). It runs on your **GPU desktop**; the
result deploys to your **laptop** fully offline.

## 1. The dataset is ready
- `annotation_frames.zip` (300 frames) — diverse frames sampled across the full
  match (both halves, both teams, ball + referees visible).
- Regenerate / add more any time:
  ```bash
  python -m vision.sample_frames --video match.mp4 --out annotation_frames --count 300
  ```

## 2. Label it (fast path)
1. Create a project at [roboflow.com](https://roboflow.com) (Object Detection).
2. Upload `annotation_frames/` (or the zip).
3. Turn on **Label Assist** and pick the `football-players-detection-3zvbc`
   model — it auto-suggests boxes. You just **correct** them and add numbers.
4. Classes to label:
   - `ball`, `player`, `referee` (a `goalkeeper` class folds into `player` via
     the pipeline's aliases), and
   - `jersey_number` — box each visible shirt number (this is what gives every
     player a permanent identity).
5. Generate a dataset **Version** (export format: YOLOv8). Add augmentations
   (brightness/blur) to help the small ball.

## 3. Train (GPU desktop)
Tip: combine your frames with the public `football-players` set for volume, and
train **big + high-res** — the ball needs it.

```bash
# From a Roboflow version:
python -m vision.train --api-key $ROBOFLOW_API_KEY \
    --workspace <your-workspace> --project <your-project> --version <n> \
    --base yolov8x.pt --imgsz 1280 --epochs 100 --device 0

# Or from a local data.yaml you exported:
python -m vision.train --data path/to/data.yaml \
    --base yolov8x.pt --imgsz 1280 --epochs 100 --device 0
```
Output: `runs/.../weights/best.pt`. Also keep a faster laptop variant:
`--base yolov8s.pt` (and optionally `yolo export model=best.pt format=onnx`).

## 4. Deploy to the laptop (fully local, no cloud/key)
```bash
# CLI:
python -m vision --video match.mp4 --model best.pt --output match_stats.json
python -m vision.bridge --stats match_stats.json --out match_data.json
```
Or in the app: **Video Analysis** page → Detection backend = **Local YOLO** →
point `--model` / "Local model weights" at `best.pt`.

## 5. Read it in the app
- **Video Analysis** — live camera + tactical map + stats.
- **Team Shape** — heatmaps, formation, shape, territory, and **Ask the analyst
  about positioning** (local Ollama Q&A over the computed findings).

## Notes
- Ball detection is the hard part — a quick CPU `yolov8n` run learned players
  (mAP50 0.92) but not the ball (~0). Hence the `yolov8x` + imgsz 1280 + 100
  epochs recommendation, with your footage in the mix.
- True pitch geometry (accurate distances/depth) needs **calibration** — a
  fixed-camera angle + 4 reference points (Phase 2 in `vision/ROADMAP.md`).
