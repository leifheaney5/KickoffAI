# Local Model Setup — laptop runbook (feed this to Claude)

Goal: get Kickoff Pulse's **local soccer detection model** running on this
machine — the GPU-trained `yolov8m` that detects ball / player / referee fully
offline (no cloud, no API key). Follow top to bottom. Hard-won gotchas are
flagged with **⚠** — don't relearn them.

## 0. Context
- The computer-vision stack lives in `vision/` (see also `vision/README.md`,
  `vision/ROADMAP.md`, `vision/ANNOTATION.md`).
- A model was trained on a desktop RTX 3080: **`soccer_yolov8m_v1.pt`**
  (yolov8m @ 1280px, ~50 MB). On the project's youth "Veo" footage it detects
  the ball in ~19% of frames and referees in ~80% — matching the Roboflow cloud
  model, but running locally.
- **The trained model (`soccer_yolov8m_v1.pt`), the annotation set
  (`annotation_frames.zip`), and the public training dataset
  (`datasets/football-players/`) ARE committed in the repo** — after `git pull`
  you already have them. Only large regenerables are gitignored: match videos,
  the ~1.6 GB `runs/` training outputs, and the `.venv`.

## 1. Environment
```bash
# from the repo root
python -m venv .venv
# Windows:  .venv\Scripts\activate     macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
pip install -r vision/requirements.txt        # the CV stack (heavy)
```

### Torch — CPU vs GPU
The install above pulls **CPU PyTorch** — fine, inference is just slower. If this
laptop has an NVIDIA GPU and you want speed:
```bash
nvidia-smi                                   # confirm a GPU + note the driver
python -c "import torch; print(torch.__version__)"   # note version, e.g. 2.12.0
# Find a CUDA wheel index that HAS that torch version (try cu126, cu128, cu130):
python -m pip index versions torch --index-url https://download.pytorch.org/whl/cu126
# ⚠ Install from the CUDA index ONLY. Do NOT add --extra-index-url pypi, and do
#   NOT rely on a plain version pin — pip will otherwise grab the +cpu build.
pip uninstall -y torch torchvision
pip install "torch==<that-version>" torchvision --index-url https://download.pytorch.org/whl/cu126
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```
**⚠ Gotcha:** `cu124` maxes out at torch 2.6; for torch ≥ 2.7 use **cu126**, and
for the very latest use **cu130**. Match the index to your installed torch
version, and to a CUDA the GPU's driver supports.

## 2. The model is already here

`soccer_yolov8m_v1.pt` (~50 MB) is committed at the repo root — `git pull`
brought it. Just verify it loads:

```bash
python -c "from ultralytics import YOLO; m=YOLO('soccer_yolov8m_v1.pt'); print(m.names)"
# expect: {0:'ball',1:'goalkeeper',2:'player',3:'referee'} (or similar)
```

## 3. Run the model
```bash
# 1) analyze a clip -> match_stats.json  (add --device 0 if you set up CUDA torch)
python -m vision --video clip.mp4 --model soccer_yolov8m_v1.pt --imgsz 1280 \
    --output match_stats.json
# 2) bridge detected passes into the dashboard's event log
python -m vision.bridge --stats match_stats.json --out match_data.json
```
Or in the app:
```bash
streamlit run dashboard.py        # or .\kickoff.ps1
```
→ **Video Analysis** page → Detection backend = **Local YOLO** → "Local model
weights" = `soccer_yolov8m_v1.pt`. Then the **Team Shape** page for heatmaps,
formation, territory, and the "Ask the analyst about positioning" Q&A.

**⚠** The positioning Q&A and Insights analyst need **Ollama** running locally:
`ollama serve` + `ollama pull llama3.2`.
**⚠** On a CPU laptop, lower `--imgsz` (e.g. 960) to speed inference up.

## 4. Getting a match clip (use 1080p)
The Video Analysis page and CLI can open a YouTube URL directly for live
analysis. For training, validation, or repeatable debugging, pull short windows
instead of downloading the whole 2+ hours.
```bash
FFMPEG=$(python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())")
python -m yt_dlp --ffmpeg-location "$FFMPEG" --download-sections "*44:20-44:50" \
    -f "bv*[height<=1080]+ba/b[height<=1080]" --remux-video mp4 \
    -o clip.%(ext)s "<YOUTUBE_URL>"
```
**⚠ Use 1080p (`height<=1080`), not 720** — the ball is tiny and resolution
directly helps detection (YOLO resizes to `--imgsz`, so more source detail =
better). 1080p files are ~2× bigger; that's fine.
**⚠** YouTube often serves **AV1**. OpenCV usually decodes AV1-in-mp4 fine, but if
`cv2.VideoCapture(...).read()` returns False, re-encode to H.264:
`ffmpeg -i clip.mp4 -c:v libx264 -an clip_h264.mp4`.

## 5. Improve the model (retrain on your footage)
The shipped model learned from the *public* football-players dataset (pro
broadcast), so ~19% ball on youth footage is the domain-gap ceiling. To beat it,
train on YOUR footage. Full guide: `vision/ANNOTATION.md`. Essentials:
```bash
# extract a diverse training set at 1080p
python -m vision.sample_frames --video match.mp4 --out annotation_frames --count 300
# (annotate ball/player/referee/jersey_number in Roboflow — Label Assist helps)
# train on a GPU:
python -m vision.train --data path/to/data.yaml --base yolov8x.pt --imgsz 1280 \
    --epochs 100 --device 0 --workers 2
```
**⚠ Keep `--workers` low (2–4)** on Windows / limited RAM — 8 dataloader workers
caused a CPU-RAM OOM at 1280px.
**⚠ Run training via the module** (`python -m vision.train ...`), never a
`python - <<EOF ... EOF` heredoc — Windows multiprocessing dataloaders try to
re-import `<stdin>` and crash.
**⚠** `yolov8x @ 1280` is heavy (~12 GB VRAM, slow); `yolov8m @ 1280` is a good
speed/quality balance for a baseline. Match `--batch` to your VRAM.

## Quick reference
| Task | Command |
|---|---|
| Check GPU in torch | `python -c "import torch;print(torch.cuda.is_available())"` |
| Sanity-check model | `python -c "from ultralytics import YOLO;print(YOLO('soccer_yolov8m_v1.pt').names)"` |
| Analyze a clip | `python -m vision --video clip.mp4 --model soccer_yolov8m_v1.pt --imgsz 1280` |
| Bridge to dashboard | `python -m vision.bridge --stats match_stats.json --out match_data.json` |
| Run the app | `streamlit run dashboard.py` |
| Pull a 1080p clip | see step 4 |
| Retrain | `python -m vision.train --data data.yaml --base yolov8x.pt --imgsz 1280 --device 0 --workers 2` |
