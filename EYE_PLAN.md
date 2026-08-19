# The Eye — ingest, live analytics, and the match-stat programme

> **Superseded by [MASTER_PLAN.md](MASTER_PLAN.md)**, which merges this with
> the Opta-style analytics specification. Kept for its detail on the two
> ingest defects and the stat taxonomy; the sequencing there is now Phase 0
> and Phases 2–5 of the master plan.


**Scope:** what the vision system takes in, what it can tell you *while the
match is still happening*, and the full match-stat taxonomy both ingests feed.
The trust gate and the report machinery are reused, not rebuilt.

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

---

# Part 2 — The match-stat programme

**Goal:** the full modern match-analysis taxonomy — everything Opta tracks —
derived our own way.

## The honest comparison

Opta puts roughly **three trained loggers** on a match and reads position from
**ten-plus calibrated cameras at 25 Hz**. We have one coach with a microphone and
one camera. Chasing parity on volume is not a plan; it is a fantasy that would
end with confident numbers built on nothing.

What *is* achievable, and is arguably worth more to a coach:

1. **The same taxonomy**, stat for stat.
2. **Each stat honestly graded.** Opta hands you a table where a hand-tagged
   shot and a modelled xG carry identical visual weight. Ours will say which is
   which. `quality.py` already does this for camera runs; the programme extends
   the idea to every metric.
3. **Every stat links to its clip.** A number in a table is a claim; twenty
   seconds of video is evidence. We shipped clips in v1.18.0 and Opta cannot
   easily do this — it is the single strongest thing we have that they do not.

## The architectural insight

**Opta's event feed is hand-tagged by humans. So is ours — that is what the Ear
is.** Our voice ingest is functionally an Opta logger, just one person instead of
three. That reframes the whole programme:

> The **event** half of Opta's taxonomy is gated on *vocabulary*, not on the
> model. The **tracking** half is gated on the retrain.

Most of what follows is therefore unblocked today.

## Where each stat comes from

Confidence descends down this list, and every metric declares which row it sits in.

| Source | Produces | Confidence today |
|---|---|---|
| **Logged** — Ear + Manual Entry | Discrete events: shots, duels, set pieces, cards | High — a human saw it |
| **Derived from events** | xG, xA, PPDA, field tilt, zone entries, sequences | High, but model-dependent |
| **Vision positions** | Shape, line height, territory, packing, pressures | *Indicative* — ~4 of 22 players detected |
| **Ball tracking** | xT, progressive carries, ball speed, chains | *Unusable* — 4–12% ball detection |

---

## S0 — The stat registry · the foundation, do this first

Today "stats" means a hard-coded list of 16 strings in `stats.py` and 13 action
weights in `insights.py`, with no definition, provenance or confidence attached
to any of them. Adding eighty more metrics to that shape would be unmaintainable
within a month.

Build `statspec.py`: one declaration per metric —

```
id, name, definition, inputs, source (logged|derived|vision|ball),
confidence_rule, unit, applies_to (team|player|both), clip_anchor
```

Everything else reads from it: the report, the season view, the UI, the CSV
export, and the trust gate. A new stat becomes one registry entry plus a
function, not an edit in nine files. `clip_anchor` is what lets any stat offer
the moments behind it.

**This is the difference between a stat programme and a pile of counters.**

## S1 — A complete event vocabulary · unblocked

We log 13 action types. Opta's F24 feed carries around a hundred. The gap is
vocabulary, and it is filled in the Ear's grammar, the Manual Entry form, and the
parser prompt — no vision work at all.

**Missing, grouped by how a coach would say them:**

- **Shooting** — body part (foot/head/other), placement, blocked, hit woodwork,
  big chance, shot situation (open play, set piece, corner, free kick, penalty,
  counter), assist, second assist, error leading to shot.
- **Duels** — aerial won/lost, ground duel, take-on (successful/failed),
  dispossessed, bad control, fouled while dribbling.
- **Defending** — block, ball recovery, last-man challenge, error leading to
  goal, pressure applied, clearance type (headed/hoofed).
- **Set pieces** — throw-in, goal kick, free kick (direct/indirect), penalty
  (scored/saved/missed), corner (short/inswinging/outswinging) and every one of
  their outcomes.
- **Goalkeeping** — save type (catch/parry/tip), claim, punch, sweeper action,
  distribution (throw/kick, short/long), save from a big chance.
- **Passing detail** — cross, through-ball, switch, long ball, key pass,
  line-breaking pass, pass into the box, pass into the final third.

Two things make this practical rather than a burden on the coach:

- **Voice grammar stays natural.** "Home nine header saved" should produce a
  shot with body part *head*, outcome *saved*, and a goalkeeper save — three
  events from four words. The parser already has an LLM; the work is prompt and
  schema, not new capture.
- **Nothing is mandatory.** Every added field is optional and absent means
  *unknown*, never zero. A coach who narrates plainly still gets today's stats.

## S2 — Derived from events · unblocked

### Expected goals, done honestly

xG is the headline modern stat and the easiest to fake. Real models train on
hundreds of thousands of shots; we would have dozens.

So: **ship a published, transparent geometric model**, not a learned one.
Distance and angle to goal, body part, situation, defensive pressure if known —
with the coefficients written down in the repo and printed in the report. Label
it a *model*, never a measurement.

A youth-calibrated, transparent model is more honest than importing a Premier
League one and quietly implying it transfers to under-14s on a smaller pitch. As
match volume grows the coefficients can be refit against our own data — which is
exactly the kind of thing owning the data makes possible.

Then: **xA** (chance quality created), and shot maps rendered with `vision/render.py`,
which already draws a pitch.

### Team-shape metrics from the event stream

- **PPDA** — opponent passes per defensive action; the standard pressing measure.
- **Field tilt** — share of possession in the final third, a better dominance
  signal than raw possession.
- **Zone entries** — final-third and penalty-box entries, and what came of them.
- **Set-piece conversion** — corners and free kicks to shots to goals, which in
  youth football is a disproportionate share of everything.
- **Possession sequences** — passes per sequence, sequence time, direct speed;
  where possession starts and how it ends.
- **Pass network** — who passes to whom, weighted, drawn on the pitch. Needs
  player attribution, which the voice log already carries.

## S3 — From vision positions · *indicative* until the retrain

All of these are computable from `vision/analytics.py` today and grade
*indicative*, exactly as possession does. Ship them labelled; they sharpen
automatically when detection improves.

- **Defensive line height** and **block length** (rear line to front line).
- **Team width and compactness** over time, not just as an average.
- **Territory** by thirds and by the eighteen-zone grid.
- **Space control** — the Voronoi tint `vision/render.py` already draws, turned
  into a number.
- **Packing** — opponents bypassed by a pass, the metric that made Impect's name.
- **Pressure events** — defenders within a radius of the ball carrier.
- **Average positions** and, once identity holds, formation.

## S4 — From ball tracking · gated on the retrain

Listed to keep them out of the near-term backlog.

- **Expected threat (xT)** — the value a possession action adds by moving the
  ball, and the modern successor to xG for non-shooting actions.
- **Progressive passes and carries**, distance-toward-goal thresholds.
- **Ball speed**, pass length and angle measured rather than described.
- **Possession chains** end to end, with xT accrued along them.
- **Distance covered, sprints, top speed** per player — needs identity as well
  as the ball.

---

## Sequencing for Part 2

```
S0 registry ──▶ S1 vocabulary ──▶ S2 derived (xG, PPDA, sequences)
                                        │
S3 vision-position metrics ─────────────┤   (indicative, ships in parallel)
                                        ▼
                              S4 ball metrics  (after the retrain)
```

| Stage | Size | Blocked by |
|---|---|---|
| S0 stat registry | M | — |
| S1 event vocabulary | L | — |
| S2 derived metrics | L | S0, S1 |
| S3 position metrics | M | — (grades *indicative*) |
| S4 ball metrics | L | The retrain |

**S0 before anything.** Every stat added before the registry exists is another
edit in nine files and another number with no stated provenance.

## What would make this genuinely better than a stats table

Three things, all of which we are uniquely placed to do:

1. **Provenance on every number.** Logged, derived or modelled — and how much to
   trust it. Nobody else in this market does it.
2. **A clip behind every stat.** Click the xG and watch the shots.
3. **Youth-calibrated models.** An xG fitted to under-14s on a small pitch,
   rather than a professional model applied where it does not belong.

## Open questions for Part 2

1. **How much narration is too much?** The full vocabulary asks more of the
   coach mid-match. The answer is probably that vision fills in over time and
   voice covers what it cannot — but the split should be deliberate, not drift.
2. **Do we publish our xG coefficients?** I would: it is the difference between a
   model a coach can argue with and a black box they have to believe.
3. **Which metrics reach a player's share pack?** xG for a striker is motivating;
   for a ten-year-old it may not be. Worth deciding per metric, not globally.
