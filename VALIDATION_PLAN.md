# Validation plan — trustworthy input, and proving what we built

Everything in this plan follows from one afternoon of running real footage
through the pipeline. It is deliberately not a feature plan: the app now has far
more capability than it has evidence, and the gap between those two is the most
valuable thing to close.

Operational layer beneath `MASTER_PLAN.md`. Where the two disagree, this one is
newer.

---

## 1. What the match test actually established

Two full runs through the live pipeline, identical settings, ten minutes each.

| Source | frames | ball | players/frame | blank frames | track ids |
|---|---:|---:|---:|---:|---:|
| Broadcast — FA Cup final | 2,959 | **7.8%** | 10.2 | **19%** | 2,237 |
| Tactical cam — Spurs v Watford | 2,219 | **1.6%** | **15.5** | **0%** | **1,105** |

Both graded **unusable** by the trust gate, correctly, and both produced zero
passes and no possession split.

Three conclusions, each measured rather than argued:

**Resolution is the binding constraint.** Every YouTube source is capped at 360p
here — six player clients tested, only `android` resolves at all, and it tops out
at 360p. At 640×360 the ball is one to three pixels across. No model finds that.

**Framing trades the ball against everything else.** A wide fixed shot fixes
cuts (19% → 0%), improves player detection (10.2 → 15.5 per frame) and halves
identity churn (0.76 → 0.50 new ids per frame) — while making the ball *worse*
(7.8% → 1.6%), because a wider shot puts it further from the lens. At 360p there
is no framing that wins both.

**Player detection is not the problem.** 15.5 players per frame on the tactical
cam, peaking at 22, with clean boxes in a congested penalty area. The detector
works. The ball and the identity permanence are what fail.

## 2. The three gaps this exposed

### 2.1 The spatial layer has never run

- **No calibration has ever been completed.** The four-point workflow shipped in
  v1.12.0 and there is no saved calibration file anywhere.
- **Every run has produced `image`-space coordinates**, never pitch metres —
  including the archived match.
- **`vision/analytics.py` has 305 lines, 16 functions and no tests.** Heatmaps,
  team shape, compactness, territory, average positions, hotspot zones. All of it
  feeds the Team Shape page and the report.

So the entire spatial half of the product is untested *and* has never been fed
valid input. We do not know whether those numbers are right — only that the trust
gate says they are uncertain.

### 2.2 Veo cannot produce fixed footage

Only the **follow-cam** view can be downloaded. Panorama and interactive views
are browser-only, and exporting the panorama is an open request on Veo's own
ideas board. The camera we own structurally cannot give the spatial analytics
what they need.

### 2.3 But the Veo download is 1080p

Three times the linear resolution of the YouTube cap: the ball goes from roughly
two pixels to roughly eight. **We have never once observed the pipeline on 1080p
footage.** Every measurement to date has been at 360p, so the ball problem has
never actually been separated from the resolution problem.

---

## Track A — One 1080p Veo export · costs nothing · clears the keystone

**The highest-leverage action available, and the only one needing no new
hardware.** Export one match from Veo at 1080p follow-cam.

It answers the question every other estimate depends on: **is ball detection
limited by the model or by the resolution?** Nothing else can separate those.

1. Export one full match, 1080p, follow-cam.
2. Run it through `scripts/live_vision.py` at the settings used above.
3. Compare against the 360p baselines in section 1.

**Success criterion, stated in advance so the result cannot be rationalised:**
ball detection above **35%** (the trust gate's `measured` threshold) means
resolution was the constraint and the retrain is far less urgent than assumed.
Between 10% and 35% means both matter. Below 10% means the model is the problem
regardless of pixels, and the retrain becomes the whole game.

4. Either way, the same file is the **annotation source for the retrain**, which
   `PHASE6_VISION_PLAN.md` has been blocked on since June.

**Known limitation:** it pans, so calibration and identity stay broken. This
track buys the ball, not the geometry.

## Track B — Validate the spatial layer · available today · no new footage

The tactical-cam material is the first footage we have where a fixed-camera
calibration is actually valid. Use it to test the untested half.

1. Grab a frame and complete the four-point calibration — the first time that
   workflow will have been run end to end.
2. Analyse a segment and confirm `coordinate_space` comes back **`pitch`**, not
   `image`. That single line has never been true.
3. Check the spatial outputs against the video by eye: does the defensive line
   sit where it looks like it sits, does compactness tighten when the team
   compresses, does territory move when play does.
4. **Write tests for `vision/analytics.py`** — 16 functions, currently zero.
5. Fix whatever is wrong. Some of it will be.

**Why now:** this closes the largest unvalidated surface in the product, needs
nothing from anyone, and half the Team Shape page may have been quietly wrong for
months.

## Track C — A fixed camera for one match · one weekend

Stage 0 of `HARDWARE_PROPOSAL.md`, now with measured backing rather than
argument.

**Height is the whole problem, not the camera.** A modern phone shoots 4K, well
past what is needed. A phone at 1.5 m on a tripod is close to useless: players
occlude each other, the far touchline is unresolvable, and the angle is too flat
to calibrate from. Roughly **4–6 m** is the target — an existing stand, a
clubhouse balcony, a bank beside the pitch, a fence line, or a painter's pole
clamped to something solid.

Two things work in our favour:

- **Youth pitches are small.** Around 64×46 m against 105×68 for full size, so a
  single fixed wide camera has a far easier job here than the tactical cam had at
  Wembley.
- **Partial coverage is fine.** Calibration holds for whatever the camera sees,
  and the trust gate reports honestly on the rest. A fixed shot covering 70% of
  the pitch is worth more to this system than a panning one covering all of it.

Record one match. Compare against Tracks A and B. Then decide whether the
Raspberry Pi rig (Stage 1) is worth building at all.

## Track D — Consolidate the plans · small · overdue

There are now **fourteen plan documents**. Several are superseded and one
contradicts another on sequencing. Fold them:

| Keep | Fold into it |
|---|---|
| `MASTER_PLAN.md` | `EYE_PLAN.md`, `E2E_DEVELOPMENT_PLAN.md`, `FEATURES_PLAN.md` |
| `PRODUCT_VISION.md` | — (strategy; stays) |
| `HARDWARE_PROPOSAL.md` | — (referenced by Track C) |
| `VALIDATION_PLAN.md` | — (this; the current operational plan) |
| `PHASE6_VISION_PLAN.md` | keep until the retrain lands, then fold |

Archive the rest under `docs/archive/` rather than deleting: they record why
decisions were made, which is worth keeping even when the plan is spent.

---

## Sequencing

```
Track A  Veo 1080p export ────▶ answers "model or resolution?" ──▶ retrain
   (you, minutes)                                                  decision

Track B  Validate spatial ────▶ closes the largest untested surface
   (me, today, no blockers)

Track C  Fixed camera ────────▶ calibration + identity, for real
   (you, one weekend)

Track D  Consolidate ─────────▶ anytime
```

A and B are independent and should run in parallel. C is worth doing whatever A
shows, because it is the only route to valid geometry. D is housekeeping.

| Track | Size | Blocked by | Answers |
|---|---|---|---|
| A Veo export | S | one export from you | Is it the model or the pixels? |
| B Spatial validation | M | — | Are the spatial numbers real? |
| C Fixed camera | M | one weekend | Can we get valid geometry at all? |
| D Consolidate | S | — | — |

## Risks

| Risk | Mitigation |
|---|---|
| The 1080p export still shows poor ball detection | That is itself the answer, and it makes the retrain the unambiguous priority rather than a guess |
| Calibration on tactical-cam footage fails because the camera pans slightly | Try it on the steadiest passage; if it will not hold, that is evidence Track C needs a genuinely static mount |
| Spatial validation finds the metrics are wrong | Better found now than after a coach has acted on them |
| Fixed camera cannot cover the pitch from available height | Exactly what Track C exists to discover, at the cost of a weekend rather than a rig |

## Open questions

1. **Which Veo plan is on this account?** Downloads need a tier above Starter,
   and full-match MP4 needs above Family. Worth checking before planning around
   an export that may not be available.
2. **Is there an elevated position at your home pitch?** It decides whether
   Track C is a tripod and a clamp or a genuine mast build.
3. **If the 1080p export shows good ball detection, does the retrain still
   matter?** Probably yes for jersey numbers and identity — but it stops being
   the thing blocking everything else, and the roadmap should be rewritten to say
   so.
