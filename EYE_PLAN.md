# The Eye — ingest and live analytics plan

**Scope:** what the vision system takes in, and what it can tell you *while the
match is still happening*. Post-hoc analysis, the trust gate and the report are
out of scope; they work.

**Where it stands.** The Eye runs as a persistent process, survives navigation,
pauses at half-time, publishes health once a second, and computes possession and
passing live. Everything spatial it is capable of — shape, territory, heatmaps,
average positions — exists in `vision/analytics.py` and runs **only after the
match**, from the saved document.

---

## Two bugs found while surveying

Both predate this plan and both should be fixed before anything is added.

### 1. A live run leaves no footage

The Eye analyses a live stream and saves `match_stats.json`. The video is never
written. So a live match produces numbers and **nothing to clip** — the clip
feature shipped in v1.18.0 only works for matches you happened to record
separately, which is not how a live match day works.

### 2. Timestamps drift by the length of every stream outage

`vision/pipeline.py` derives event time from the frame counter:

```python
t_sec = self._raw_index / self._source_fps
```

`_raw_index` counts frames **received**, not time **elapsed**. During a dropout
no frames arrive, so the counter stops while the match does not. Worked through:

| | |
|---|---|
| 10 min analysed, 60 s outage, 5 min more | |
| Time the app reports | **15.0 min** |
| Time that actually passed | **16.0 min** |
| Error on every subsequent event | **60 s early** |

It compounds with each reconnect, and it propagates: `vision/bridge.py` stamps
vision events as `kickoff + t_sec`, so a drifted clock produces drifted
wall-clock timestamps, which **cuts clips in the wrong place**. The fix is to
derive time from the wall clock and use the frame counter only for indexing.

---

## Tier 1 — Ingest · unblocked, fixes real defects

### A1. Record while analysing

Tee the incoming stream to disk alongside analysis, the same pattern
`scripts/rig_capture.py` already uses for the rig: one source, two sinks, the
file written first so a failure of the analysis never costs the footage.

Unlocks clips, share packs and the retrain's annotation supply for *every* live
match rather than only recorded ones. This is the highest-value item in the plan.

### A2. Wall-clock event time

Replace the frame-counter clock with wall clock, keeping the counter for frame
indexing. Removes the drift above and makes vision events align with audio events
and with the video by construction rather than by luck.

### A3. Live-edge discipline

`step()` reads sequentially and skips by stride. If inference is slower than
real-time on a **live** source, frames queue in the decoder and the analysis
falls progressively further behind the live edge, with no mechanism to catch up.
An hour into a match the "live" view could be minutes stale.

Needed: measure the gap between wall clock and the frame being processed, and
when it exceeds a threshold, drop frames to return to the live edge — reporting
what was skipped rather than hiding it.

### A4. Source telemetry

`run_quality` records what we chose (model, stride, imgsz) but almost nothing
about what actually arrived: resolution changes mid-stream, decode errors,
dropped frames, effective bitrate. These are the first symptoms of a feed going
bad, and today the only signal is fps quietly falling.

### A5. Adaptive quality

Stride and image size are fixed for the run. When the machine cannot keep up the
right response is to degrade deliberately — raise the stride, drop the inference
size — and say so, rather than silently falling behind (A3) or thermally
throttling. Bound it so the trust gate can still read the run honestly.

### A6. Pre-roll buffer

Keep a rolling ~60 s of decoded frames so pressing **Start** captures the minute
*before* the click. Kickoff is never at the moment someone reaches the laptop.

---

## Tier 2 — Live analytics · unblocked, value scales with the model

Everything here reuses `vision/analytics.py`, which already computes it — the
work is streaming it rather than waiting for the saved document.

**Caveat stated plainly:** on current footage the model finds ~4 players per
frame against a true 22. Shape and territory degrade more gracefully than
ball-dependent stats — a partial squad still yields a centroid and a rough block
— but these land as *indicative* until the retrain, and the trust gate should
grade them exactly as it grades possession today.

### B1. Live shape, territory and centroid

Stream what Team Shape shows after the match: each side's centroid, width and
depth, compactness, and the thirds split. A coach watching a defensive block
stretch has something to act on *during* the half, which is the only time it is
actionable.

### B2. A continuous vision contribution to momentum

Momentum currently moves only when a discrete event is bridged. Territory and
possession are continuous signals the Eye already has; feeding them in makes the
curve responsive between events. Weighted by run quality, exactly as bridged
vision events already are.

### B3. Ball trajectory and speed

Positions over time are recorded and never differentiated. Speed and direction
are the substrate for shot detection, clearance-versus-pass, and out-of-play —
and are cheap once the ball is reliably found.

### B4. Live alerts

The console records; it never advises. With B1–B3 there is enough to say "Away
have had three shots in eight minutes" or "your block has dropped fifteen metres
since the break". This is what turns the Eye from a recorder into a second pair
of eyes, and it is the feature most likely to be *used* during a match.

---

## Tier 3 — Gated on the retrain

Listed so they are not started early. All depend on detection quality the model
does not have yet.

- **Event detection beyond passes** — shots, crosses, clearances, corners,
  out-of-play. Needs a reliably tracked ball.
- **Per-player live metrics** — distance covered, sprint counts, minutes. Needs
  identity that survives occlusion; today ~75 track-ids appear for ~22 players.
- **Formation detection** — average positions by role, which needs identity to
  mean anything.
- **Multi-camera / panorama ingest** — Stage 3 of `HARDWARE_PROPOSAL.md`.

---

## Sequencing

```
A2 wall clock ──┐
A1 record ──────┼──▶ clips + retrain supply + correct timing   (do first)
A3 live edge ───┘

A4 telemetry ──▶ A5 adaptive quality                           (reliability)

B1 shape ──┬──▶ B2 momentum ──▶ B4 alerts                      (coaching value)
B3 ball ───┘

Tier 3                                                          (after retrain)
```

| Item | Size | Why now |
|---|---|---|
| A2 wall clock | S | A correctness bug that corrupts clips |
| A1 record while analysing | M | Live matches currently produce no footage at all |
| A3 live-edge discipline | M | "Live" silently stops being live |
| A4 telemetry | S | First warning that a feed is failing |
| A5 adaptive quality | M | Degrade honestly instead of drifting |
| A6 pre-roll | S | Kickoff is never when someone reaches the laptop |
| B1 shape/territory | M | Reuses existing analytics; actionable in-half |
| B2 momentum | S | Small, once B1 streams |
| B3 ball speed | M | Substrate for Tier 3 |
| B4 alerts | M | The feature most likely to be used live |

**Recommended first pass: A2 + A1 + A3.** They are a single coherent release
about the ingest being correct, complete and actually live — and A1 is what makes
every match clippable.

## Open questions

1. **Where should live recordings go?** They are gigabytes per match and the
   retention policy added in v1.14.0 covers `recordings/` only. A live run
   writing there inherits pruning, which may or may not be wanted for match
   footage you intend to keep.
2. **Should adaptive quality (A5) be allowed to change stride mid-run?** It keeps
   the run alive, but it makes the sampled frame rate non-constant, which the
   schema's `frame_rate_sampled` currently assumes is fixed.
3. **How loud should alerts (B4) be?** A coach mid-match has very little
   attention. Probably two or three signals per half, not a feed.
