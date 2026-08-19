# End-to-end development plan — capture to season

**From:** v1.12.1 (vision-first ingest shipped)
**Through:** a trustworthy match record that flows capture → fusion → report →
library → season.

> **Status (v1.13.0):** Phases A (bar the live soak test), B, E and F are
> implemented. Phase C is blocked on a 1080p Veo export and Phase D on Phase C.
> Per-phase status is marked inline below.

The app now captures a match from a camera feed. What it does not yet do is
*combine* what the Eye sees with what the Ear hears into one record, carry the
distinction through to the library, or tell you whether a given run's numbers can
be trusted. This plan closes that path end to end.

---

## The organising idea: an honest trust gate

One fact shapes everything below. On the current 360p footage the Eye detects the
ball in **4–12% of frames** (measured during the v1.12.0 runner tests; the repo's
own [vision/NEXT_STEPS.md](vision/NEXT_STEPS.md) records ~19% on a better clip).
Possession and passing are ball-dependent, so **every ball-derived number the app
produces today is directional at best**.

There are two wrong responses. One is to block all downstream work until the
model improves — that wastes the months before a 1080p export exists. The other
is to ship vision stats into the coach report as if they were measured, which
quietly makes the report *less* trustworthy than the audio-only one it replaces.

So the plan is built around a third option: **make trust a first-class, computed
property of every run**, ship the full pipeline behind it, and let the numbers
become authoritative automatically when the model earns it.

```
ball_rate + calibration + reconnects  ─▶  run quality  ─▶  indicative | measured
                                                              │
                        report labels, momentum weighting, season inclusion
```

A run below threshold still produces everything — charts, momentum, archive — it
is just labelled *indicative* and excluded from season aggregates. Nothing is
hidden, nothing is overclaimed, and the retrain flips runs to *measured* with no
further code changes.

---

## Where each stage actually stands

| Stage | State today | Gap |
|---|---|---|
| **Capture — vision** | Persistent runner, UI controls, health file, pause/resume | Never soak-tested on a live 90-minute Veo stream |
| **Capture — voice** | Working, now opt-in backup | — |
| **Notes** | Written + spoken, flow to report and library | — |
| **Fusion** | `bridge.convert()` maps **passes only**; `bridge.possession_of()` exists and is **called by nothing** | Vision possession never reaches the report |
| **Momentum** | [insights.py:96-98](insights.py#L96-L98) knows sources `audio` and `momentum` | No vision source |
| **Report** | Possession computed from audio via `S.possession()` ([report.py:595](report.py#L595)) | No vision section, no run-quality statement |
| **Archive** | `finalize.py` stores `match_stats.json` as an opaque media blob | Not parsed; nothing queryable |
| **Archive — provenance** | `bridge.py:137` tags events `source`, but [finalize.py:134-138](finalize.py#L134-L138) **drops it**; `db.Event` has no `source` column | Archived matches can't tell Eye from mic |
| **Season** | Standings + top scorers from goals only ([season.py](season.py)) | No vision metrics across matches |

Two of these are outright dead ends in the current code — `possession_of()` that
nothing calls, and a `source` tag that gets dropped at the archive boundary. Both
are small fixes that unblock everything downstream.

---

## Phase A — Harden the live path

**Status: 3 of 4 done.** Steps 2 and 4 shipped in v1.13.0; step 1
(live soak) still needs a real Veo stream URL, step 3 needs a deliberate
mid-run network drop.

**Blockers:** a live feed to test against.

Everything else assumes a 90-minute run completes cleanly. That has never been
demonstrated.

1. **Soak test on a live Veo `.m3u8`** — a full half minimum. Record fps decay,
   memory, reconnect count, thermal behaviour, and whether the HLS token
   survives. This is the single highest-consequence unknown in the system.
2. **Measure and fix checkpoint cost.** The runner rewrites the *entire*
   `match_stats.json` every 10 seconds. The existing files are 4.7 MB and
   16.5 MB. If a 90-minute run sits near 5 MB that is ~2.5 GB of writes and a
   full serialize competing with inference on the same thread. Time one save
   first; if material, either lengthen the interval, write frames incrementally,
   or move the save off-thread.
3. **Validate reconnect** by deliberately dropping the network mid-run and
   confirming `reconnect_count` rises and analysis resumes from the live edge.
4. **Post-match run readout.** Ball rate, frames, fps, reconnects, calibration
   state are visible live and then lost. Persist them into `match_stats.json` as
   a `run_quality` block — this is the raw material for the trust gate and for
   every judgement downstream.

**Done when:** a full half runs unattended on a live feed, and its
`match_stats.json` carries a `run_quality` block describing how it went.

---

## Phase B — Fusion, behind the trust gate

**Status: DONE (v1.13.0).** All six steps shipped.

1. **Compute run quality.** A small pure module (`quality.py`) turning
   `run_quality` into `indicative | measured` plus the reasons. Thresholds live
   in one place and are tunable as the model improves. Pure functions, easily
   tested — no vision deps, so it runs in CI.
2. **Carry provenance to the archive.** Add `source` to `db.Event`, map it in
   `finalize.py`, and backfill existing rows as `audio`. Without this, no
   cross-match vision analysis is possible at all.
3. **Vision possession into the report — as its own series.** Wire up the dead
   `bridge.possession_of()`. Show audio and vision possession **side by side,
   labelled**, never blended. Two honest numbers beat one invented one, and when
   they disagree that disagreement is itself information for the coach.
4. **Momentum gains a `vision` source.** Passes, possession swings and territory
   feed [insights.py](insights.py) alongside audio events. Weight vision
   contributions by run quality so a poor run cannot dominate the curve.
5. **Key-moment tagging.** Fuse the two streams into moments — an audio "goal"
   anchored to the vision possession swing around it. This is the payoff of
   fusion and the thing neither stream can produce alone.
6. **Report states its own trustworthiness.** A one-line provenance note: which
   ingests ran, the run's quality verdict, and why. A coach should never have to
   guess whether a possession figure was measured or inferred.

**Done when:** a report shows both possession series, momentum blends both
sources, and the document says plainly how much to trust it.

---

## Phase C — The keystone: retrain

**Status: BLOCKED on you** — a **1080p match export from Veo**. No code can
clear this. Everything else is built and waiting for it.

This is the repo's long-standing keystone ([PHASE6_VISION_PLAN.md](PHASE6_VISION_PLAN.md)),
and it is what flips Phase B's runs from *indicative* to *measured*.

1. Re-extract frames at 1080p (`vision.sample_frames`) — current annotation
   frames are 720p and the ball is too soft.
2. Annotate **ball, player, referee, jersey_number** (Roboflow + Label Assist).
3. Train on the GPU (`vision.train`), deploy over `soccer_yolov8m_v1.pt`.
4. **Validation gate:** re-run a known clip and compare ball rate, possession and
   pass count against the pre-retrain baseline. Record both in the changelog —
   this is the number that justifies the whole effort.
5. Re-tune the trust thresholds from Phase B against the new reality.

**Done when:** ball detection clears the threshold that lets a normal run
self-report as *measured*.

---

## Phase D — Identity and per-player truth

**Status: BLOCKED on Phase C** emitting `jersey_number`.

The OCR binder is already scaffolded in `vision/teams.py` and `vision/pipeline.py`.
Today ~75 track-ids appear for ~22 players, so per-player vision stats are
meaningless.

- Turn on jersey-number binding; measure track fragmentation before and after.
- Per-player distance, minutes and heatmaps into the report and the library.
- Feed per-player vision stats into season aggregates.

---

## Phase E — Season-level intelligence

**Status: DONE (v1.13.0)** for possession trend + camera coverage. Team-shape
evolution still wants Phase C-grade data to be worth trending.

[season.py](season.py) currently aggregates goals into standings and top
scorers — nothing spatial, and no vision at all.

- Possession, pass volume and territory trends across matches.
- Team-shape evolution over a season.
- **Only *measured* runs enter season aggregates.** Mixing an indicative run into
  a season trend silently corrupts it, which is exactly what the trust gate is
  for.

---

## Phase F — Debt and decisions

**Status: docs + renderer logging DONE (v1.13.0).** The second-half alignment
decision is still open — it is a call for you, not a task.

- **Stale docs.** [vision/NEXT_STEPS.md](vision/NEXT_STEPS.md) still lists manual
  4-point calibration as "not-yet-built" — it exists and now lives on Camera &
  Feed — and flags a hardcoded CPU device that is now a selector.
  [vision/ROADMAP.md](vision/ROADMAP.md) still points at `pages/4_Video_Analysis.py`,
  which no longer exists.
- **Second-half alignment — a decision, not a task.** You have
  `match_stats_2ndhalf.json` as a separate document, and the `analyze-video`
  skill warns that second-half footage isn't time-aligned to the audio log.
  v1.12.0's Half button now pauses and resumes the Eye *within one document*,
  which may have solved this or may conflict with the two-file habit. Pick one
  model before building anything that reads across halves.
- **Momentum renderer divergence.** The matplotlib and Pillow paths produce
  visibly different charts (saturated vs pale fills, dotted vs solid goal
  markers). Fine for CI; worth logging which renderer ran so a surprising-looking
  report is explainable.

---

## Sequencing

```
A. Harden live path ──▶ B. Fusion + trust gate ──┬──▶ E. Season intelligence
   (no blockers)          (needs A)              │
                                                 │
C. Retrain ──────────────────────────────────────┴──▶ D. Identity
   (BLOCKED: 1080p export)                              (needs C)

F. Debt — anytime, in parallel
```

A → B is the critical path and is entirely unblocked. C runs in parallel the
moment you produce the footage; it does not gate A or B, it *upgrades* their
output. Phases D and E are where the compounding value lives, but neither is
reachable without B's provenance work.

| Phase | Size | Blocked by | Ships value before retrain? |
|---|---|---|---|
| A Harden | M | — | Yes — makes match day safe |
| B Fusion | L | A | Yes — honest fused report |
| C Retrain | L | **your 1080p export** | It *is* the unlock |
| D Identity | M | C | No |
| E Season | M | B (+C for trust) | Partly |
| F Debt | S | — | Yes |

---

## Risks

| Risk | Consequence | Mitigation |
|---|---|---|
| Live stream fails mid-match | Lose a whole match's vision data | Phase A soak test; reconnect validation; checkpoints already bound loss to ~10s |
| Checkpoint I/O starves inference | Silent fps decay, worse stats | Measure in A before optimising — may be a non-issue |
| Fusion ships before trust gate | Report becomes *less* trustworthy than audio-only | Gate is Phase B step 1, before any fused number reaches the report |
| Retrain never unblocks | D and E stay out of reach indefinitely | A, B, F all deliver standalone value; nothing is staged behind C except D |
| Indicative runs pollute season data | Season trends quietly wrong | Explicit exclusion rule in E |

---

## What I'd do first

Phase A, step 1 — the live soak test. It is the cheapest task here, it is the
only one that can ruin a real match day, and everything downstream assumes it
works. Then A's `run_quality` block, which is the foundation the whole trust gate
stands on.

If you can get the 1080p export queued in parallel, C stops being a blocker and
starts being an upgrade that lands whenever it lands.

## Open questions

1. **Trust thresholds.** What ball rate makes a run *measured*? Suggest starting
   at 35% and tuning after the retrain, but that is a guess until Phase C gives
   real data.
2. **Possession disagreement.** When audio and vision disagree sharply, does the
   report flag it explicitly, or just show both? Plan assumes show both, flag
   only when the gap exceeds a threshold.
3. **Season inclusion.** Should an *indicative* run contribute to standings
   (which are goal-based and unaffected by vision quality) while being excluded
   from possession trends? Plan assumes yes — the exclusion is per-metric, not
   per-match.
