# Footage

The Eye's numbers are only as good as the footage under them, and two properties
of a video decide almost everything: whether the camera moves, and how many
pixels the ball occupies at inference time. Both are measurable, both have been
measured, and both have been wrong when assumed.

This is the record of what was measured, how, and what it means for a run.

## The standing rule: camera motion is measured, never inferred

A pitch calibration is a single homography, and a homography is only valid while
the view does not change. The instant a camera starts following play, every
position, distance and zone the Eye produces is wrong — and wrong in a way
nothing downstream can detect on its own. `quality.assess()` can only warn after
the fact ("calibrated, but the camera pans"). So whether a camera is fixed is not
a footnote; it decides whether a match's spatial output means anything.

Titles do not answer that question. Two clips in the corpus below are titled
"tactical camera" and pan by 3-4 px a second. One titled "Panorama" turned out to
be the most static footage found. "Tactical cam" is a marketing term, not a
mounting specification.

**Run `scripts/footage_probe.py` on any new source before trusting a run from
it.** A verdict of `pans` or `cuts` means a calibration cannot hold, and the run
is image-space at best.

## How the measurement works

`scripts/footage_probe.py` samples one frame per second, downscales each to
320x180 grayscale float32, and runs `cv2.phaseCorrelate` on consecutive samples.
Phase correlation finds the peak of the cross-power spectrum of two frames, which
gives the global translation between them to sub-pixel precision plus a response
saying how sharp the peak was.

Two properties make it the right tool:

- It is a whole-frame measurement. A dozen players running are a small fraction
  of the pixels and do not move the estimate. A camera pan moves every pixel and
  does.
- The response doubles as a scene-change detector. Two frames from two different
  cameras share no structure, so the peak collapses instead of shifting.

One sample per second is deliberate: consecutive video frames of a slow pan
differ by a fraction of a pixel, below the noise floor, while a one-second
baseline turns the same pan into something measurable.

```
python scripts/footage_probe.py "https://www.youtube.com/watch?v=2ZKZwKKiCL8" --at 600 --for 120
python scripts/footage_probe.py recordings/match.mp4 --at 600 --for 120 --detail
python scripts/footage_probe.py a.mp4 b.mp4 c.mp4 --json
```

The probe is read-only. It writes nothing but its report.

### Thresholds and why they are there

All shifts are in **probe pixels** — pixels of the 320x180 downscale, not of the
source. One probe pixel is 6 source pixels at 1080p and 12 at 4K.

| Threshold | Value | Why |
|---|---|---|
| `FIXED_PX` | 0.15 px/s | Phase correlation is a sub-pixel estimator; between two genuinely identical scenes, encoder noise still shifts the fitted peak by a few hundredths of a pixel. Below 0.15 "it moved" is indistinguishable from "the estimator jittered". |
| `NEAR_FIXED_PX` | 1.0 px/s | About 6 px/s at 1080p: mount flex in wind, or a tripod settling. Not a camera following play. The real justification is that the gap is not marginal — every fixed-mount clip measured under 0.7, every auto-following one over 2.9. |
| `CUT_RESPONSE` | 0.05 | The response is the normalised peak height. Consecutive samples of one scene score near 1.0 even while panning; two unrelated frames score under 0.01. 0.05 sits in the empty middle. |
| `CUT_SHIFT_PX` | 40 px | The other face of a cut. When two shots share structure (same stadium, same crowd) the peak does not collapse, it lands somewhere arbitrary. 40 px is a quarter of the probe frame; no usable camera pans that far in a second. |
| `CUT_RATE_BROADCAST` | 1.0 cuts/min | One discontinuity in a two-minute probe is a dropped segment or a camera flash. A directed broadcast cuts every few seconds. |

Verdicts:

| Verdict | Meaning |
|---|---|
| `fixed` | Bolted down. One calibration holds for the whole match. |
| `near-fixed` | Drifts under a pixel a second. One calibration still holds. |
| `pans` | The camera follows play. A fixed homography goes stale; reject. |
| `cuts` | A cut broadcast, not single-camera footage. Unusable for tracking. |
| `unknown` | Not enough samples to say. Never read this as "fixed". |

Cuts are excluded from the shift statistics: a cut is not camera motion, and one
80 px jump would otherwise become a still camera's reported "max pan".

## The verified corpus

Every row below was measured with the method above, not read off a title. All
are YouTube IDs.

| ID | Match | Median shift | Verdict | Max res | Duration |
|---|---|---|---|---|---|
| `T2TAHYKo3UU` | Real Madrid v Barcelona, tactical cam | 0.22 px | near-fixed. Best landmarks of the set: penalty box, centre circle and both touchlines visible, so calibration is straightforward | 1080p | 121 min |
| `2ZKZwKKiCL8` | Panorama vs Randburg (amateur, LMSPORTS) | 0.09 px | **fixed** — the most static footage found | 4K, 3840x2160 | 72 min |
| `M9mKnmt0YaM` | Man City v Chelsea, VIP tactical cam | 0.61 px | near-fixed. Tighter framing, so fewer landmarks to calibrate against | 1080p | 95 min |
| `aHByCYiqpIA` | Tottenham v Watford, tactical cam | not recorded | The benchmark baseline; all resolution arms below ran on this match | 1080p | not recorded |
| `6lAbqQIvQUo` | Spain v Argentina, "tactical camera" | 2.94 px | **pans** — rejected despite the title | not recorded | 142 min |
| `86zhlXNNUZI` | England v Uruguay, "tactical cam" | 3.77 px | **pans** — rejected despite the title | not recorded | 128 min |
| `SHLzUCSMGC4` | Clemson v Pittsburgh | 0.19 px | Rejected: it is American football, not soccer. The camera is fine; the sport is not | 720p | 110 min |

Notes on choosing from this list:

- `T2TAHYKo3UU` is the default choice for anything that needs a calibration. It
  is near-fixed *and* shows enough pitch landmarks to place them accurately.
- `2ZKZwKKiCL8` is the strictest test of fixed-camera assumptions and the only
  4K source, so it is the one with headroom for high inference sizes. It is also
  amateur footage, which makes it the closest match to the youth games this app
  is actually for.
- `M9mKnmt0YaM` is a usable second opinion, but its tighter framing gives fewer
  landmarks, so expect a rougher calibration.
- The two panning clips are worth keeping precisely because they are rejects.
  They are the regression cases for the probe: if a change to the probe ever
  calls either of them fixed, the change is wrong.

The medians come from the original measurement runs of the same method. Re-run
the probe if a figure matters to a decision; the last decimal place depends on
which segment is sampled, and the recorded window per clip was not kept.

## Detection quality depends enormously on inference resolution

The second measured result. Three arms, same model, same 10-minute segment of the
same match (`aHByCYiqpIA`), varying only the source resolution and the inference
size:

| Arm | Source | `imgsz` | Ball detection rate |
|---|---|---|---|
| 1 | 360p | 960 | 2.2% |
| 2 | 1080p | 960 | 6.6% |
| 3 | 1080p | 1920 | **33.2%** |

A fifteenfold swing with no change to the model, the footage or the thresholds.
The reason is physical: a ball is a handful of pixels at tactical-camera framing,
and shrinking the frame before inference leaves nothing to detect. Both halves
matter independently — feeding a higher-resolution source through the same small
`imgsz` only tripled the rate (arm 1 to arm 2), because the frame is downscaled
before the model ever sees it. The large win came from letting the model see
those pixels (arm 2 to arm 3).

Read against `quality.py`, which grades a run from its ball-detection rate:

- 2.2% and 6.6% are below `BALL_RATE_INDICATIVE` (10%). Those runs are
  **unusable** — the report will not state their possession or passing at all.
- 33.2% clears `indicative` comfortably but still falls short of
  `BALL_RATE_MEASURED` (35%). Even the best arm produces directional numbers, not
  measured ones.

So the practical floor for a run worth generating a report from is a 1080p or
better source at `imgsz` 1920. Anything less is not a slightly worse run, it is a
run whose vision figures get suppressed.

### Reproducing it

`scripts/benchmark.py` runs the comparison. An arm is `[label=]video@imgsz`;
every other setting is shared across arms, so any difference in the table is
caused by the thing being varied.

```
python scripts/benchmark.py \
    360p=/footage/tottenham_360p.mp4@960 \
    1080p=/footage/tottenham_1080p.mp4@960 \
    1080p-hi=/footage/tottenham_1080p.mp4@1920 \
    --at 600 --seconds 600 --out benchmarks/imgsz.json
```

It reports frames, ball detection rate, players per frame, blank frame rate,
distinct track ids, and wall clock per arm, and writes the same figures as JSON.

Two things it does deliberately:

- **It never writes `match_stats.json` or `match_data.json`.** The live runner
  defaults to both; a benchmark that inherited those defaults would overwrite a
  real match with test data. Per-arm output goes under `--out-dir`, and the
  protected names are refused outright.
- **It re-executes itself under `caffeinate -i`** on macOS, and separately
  detects machine suspension by comparing the monotonic clock (which stops while
  the machine is asleep) with the calendar clock (which does not). Two earlier
  runs of this comparison were destroyed by the Mac sleeping mid-benchmark, one
  reporting 26120 seconds of wall clock for a few minutes of work. Now the sleep
  is reported as its own figure with a warning, rather than being folded silently
  into the result. `caffeinate -i` blocks idle sleep only; closing the lid still
  sleeps the machine, which is why the detector exists as well as the wrapper.

## Fetching the footage: yt-dlp must be current

An out-of-date yt-dlp silently caps YouTube downloads at 360p. It does not error,
it just hands back the low-resolution stream. That cost this project a wrong
conclusion once — that YouTube itself was capped at 360p and higher-resolution
match footage was unobtainable — which in turn made the resolution benchmark
above look impossible to run.

Before measuring anything, update it and confirm what the source actually offers:

```
pip install -U yt-dlp
yt-dlp -F "https://www.youtube.com/watch?v=2ZKZwKKiCL8" | head -40
```

If the format list tops out at 360p on a video that is plainly higher resolution,
the tool is stale, not the video. The probe reports the frame size it actually
opened for the same reason: it is the cheapest way to catch this.
