# Kickoff Pulse — Vision Development Plan

A staged roadmap to turn match video into **spatial intelligence**, fully local,
complementing the audio tracker. Sequenced to the available assets (Veo footage,
a GPU desktop, a laptop) so it ships value at every step.

## North star
**Audio owns *events*. Vision owns *space*.** The audio tracker already logs
goals/cards/shots; vision adds positioning, shape, heatmaps, movement and —
eventually — possession/passing. Everything runs **local-first** (laptop,
offline); cloud is a development convenience only.

## Guiding principles
1. **Local-first** — the laptop path uses a local `.pt` + on-device OCR + manual
   calibration. No key, no network.
2. **Footage-aware** — tune to the actual Veo youth footage, not generic broadcast.
3. **Tiered ambition** — ship robust *player-space* analytics now; gate
   *ball-dependent* stats on data quality.
4. **Train big, run small** — fine-tune `yolov8x` on the desktop GPU; deploy a
   `yolov8s` variant to the laptop.
5. **Correct before fancy** — calibration (real metres) is the foundation
   everything trustworthy depends on.

## What each metric needs

| Metric | Player det. | Stable ID | Calibration | Ball | When |
|---|:--:|:--:|:--:|:--:|---|
| Team heatmap | ✓ | – | better | – | Now |
| Team shape / compactness / width-depth | ✓ | – | better | – | Now |
| Territory (thirds) | ✓ | – | better | optional | Now |
| Per-player heatmap | ✓ | ✓✓ | better | – | Now (clips) → reliable Ph.4 |
| Formation (avg position by role) | ✓ | ✓ | ✓ | – | Ph.2 / Ph.4 |
| Distance covered / speed | ✓ | ✓ | ✓✓ | – | Ph.2 + Ph.4 |
| Possession | ✓ | ✓ | ✓ | ✓✓ | Ph.5 |
| Passes / pass network | ✓ | ✓ | ✓ | ✓✓ | Ph.5 |

The ball and stable identity are the two scarce resources. The early analytics
deliberately avoid both.

## Architecture (Phase 0 — done)
```
video ─▶ detection (Ultralytics YOLO  OR  Roboflow cloud) ─▶ tracking (BoT-SORT/ByteTrack)
      ─▶ identity permanence ─▶ homography (static 4-pt OR per-frame pitch keypoints)
      ─▶ teams (HSV K-Means) + jersey OCR ─▶ heuristics (possession/passing)
      ─▶ match_stats.json ──▶ bridge ──▶ match_data.json (live dashboard/timeline)
      └─▶ pages/4_Video_Analysis.py  (live camera + tactical map + stats)
```

## Phased roadmap

### Phase 1 — Spatial analytics that work today · M · no blockers
- `vision/analytics.py` — heatmaps, average positions, team shape (centroid,
  width/depth, compactness), territory. Pure, offline.
- `pages/5_Team_Shape.py` — heatmaps (team & per-player), formation diagram,
  shape metrics, territory bars.
- Image-space now; auto-upgrades to pitch-accurate after Phase 2.

### Phase 2 — Calibration → real metres · M · blocked on fixed-panorama export
- Manual 4-point pitch calibration in the UI; persist the homography.
- Real-metre heatmaps, distances, formation; re-projection validation overlay.

### Phase 3 — Custom model + local deployment · L · needs GPU + annotation
- Dataset = Roboflow `football-players-detection` + annotated frames of the
  actual Veo footage (domain gap is real).
- Train on desktop GPU (`vision/train.py`) → `best.pt` + a `yolov8s` laptop
  variant; export ONNX/TensorRT; fully-local laptop inference path.

### Phase 4 — Identity & per-player reliability · M · needs Phase 3 jersey numbers
- Jersey-number OCR binding (already scaffolded) → permanent ID anchoring.
- Re-ID tuning for occlusions. Unlocks reliable per-player heatmaps, distance,
  minutes.

### Phase 5 — Ball-dependent analytics · L · needs Phase 2 + Phase 3
- Possession, passes, pass network, territory pressure, simple xT.
- Possession widget on the main dashboard.

### Phase 6 — Productionize · M · ongoing
- Performance (batching, half-precision, ONNX/TensorRT, smart skip).
- 90-minute robustness (streaming NDJSON output, dropout recovery, halves).
- Reports (heatmaps/shape into `report.py`), offline laptop packaging, tests.

## Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Ball detection weak on youth footage | possession/passes blocked | annotate own footage; defer Ph.5; lean on audio for events |
| ID drift over 90 min | per-player stats noisy | jersey OCR (Ph.4); team-level metrics first |
| Panning / nonstandard pitch | calibration fails | fixed panorama export + manual 4-pt (Ph.2) |
| Laptop CPU too slow | not real-time | `yolov8s` + ONNX + frame-skip (Ph.3/6) |
| Annotation effort | slows Phase 3 | start with Roboflow set, add frames incrementally |

## Immediate next steps
1. **Phase 1 now** — `vision/analytics.py` + Team Shape & Heatmaps page.
2. Stand up the annotation loop so Phase 3 data accrues in the background.
3. When the fixed panorama arrives → Phase 2 calibration.
