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

**Resolution is the binding constraint.** At 640x360 the ball is one to three
pixels across and no model finds it.

> **Superseded 2026-08-20.** This section originally read "every YouTube source is
> capped at 360p here - six player clients tested". That was wrong, and it is left
> visible rather than quietly edited because the error shaped three plans. The cap
> was a **stale yt-dlp**: the venv ran Python 3.9, yt-dlp had dropped 3.9, and pip
> silently held a 10-month-old build while reporting success. A current build
> resolves 1080p and 4K on the identical URLs. Six player clients were tested when
> the variable was the tool's age. See `docs/FOOTAGE.md` and `depcheck.py`.

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

## Track B — Validate the spatial layer · MOSTLY DONE v1.24.0

Done, with the approach changed once it met reality:

Picking pitch landmarks by eye from a 640x360 still is guesswork, and a sloppy
homography would have been blamed on the analytics. So the layer was validated
against **known-answer synthetic geometry** instead — a sideline trapezoid whose
correct output can be derived by hand — which tests the maths far harder than one
hand-clicked calibration would have.

- **49 tests added** across `vision/analytics.py` (16 functions, previously zero)
  and `vision/calibration.py`. Every expected value is computed by hand, not
  captured from a run, so the suite fails when the maths changes rather than when
  the output changes.
- **The homography is correct.** Corners land on corners; the image centre column
  maps to pitch x=52.5 m at *every* image height (an affine fit or a transposed
  matrix would break this); and foreshortening is real — image mid-height maps to
  pitch 62.5, not 50. A linear stretch would have looked plausible on a heatmap
  while being wrong by 12 metres.

Two genuine bugs found and fixed:

1. **`--fixed-camera` was never applied.** The flag was parsed and reported in
   the status file, but the live runner built `MatchAnalyzer(cfg)` with no
   homography. *Every live run would have reported image space however carefully
   the pitch had been calibrated* — so the missing calibration file was only half
   the reason the spatial layer had never run.
2. **Flank labels were not attack-relative.** `_zone_label` flipped the thirds for
   a team attacking the other way but not left/right, so a label mixed a
   team-relative third with an absolute touchline: "attacking third / left" named
   the wrong wing for one of the two teams, in the digest handed to the analyst.

CI now installs `opencv-python-headless` so the geometry is checked there too,
rather than only on a dev box.

**The join is tested too.** `_project` is the one place pixels become pitch
coordinates, so it is where a calibration silently going unused would show up —
the exact shape of the `--fixed-camera` bug. It now has tests both ways, and one
that quantifies what calibration buys rather than asserting it: for the same
pixel in the same frame, the uncalibrated fallback is wrong by **8.5 metres**,
because it puts a player on the halfway line across the width while the
calibrated projection knows the far half is squeezed into fewer pixels.

**Ready for the footage.** Calibrating from a recording used to grab frame 0 —
whenever record was pressed, with the camera still being levelled. Camera & Feed
now offers a seek for file sources, so a frame with the pitch lines clearly in
view can be picked instead. `grab_frame` and `file_duration_seconds` moved out of
the page into `vision/sources.py` where they are testable and reusable.

**Still open — needs Track A or C footage:** no calibration has yet been run
against real video, so `coordinate_space` has still never actually read `pitch`
on a match. The path is now proven, tested end to end, and the workflow that
feeds it has had its sharp edge removed. It needs footage worth pointing it at.

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

## Track D — Consolidate the plans · DONE v1.24.0

There were **fourteen plan documents**; several were superseded and one
contradicted another on sequencing. Nine are now archived under
`docs/archive/`, with a README mapping each to the version that shipped it —
they record why decisions were made, which outlives the plan itself. Five
remain live:

| Live plan | Scope |
|---|---|
| `VALIDATION_PLAN.md` | This — the current operational plan |
| `MASTER_PLAN.md` | The analytics engine, phases 4-9 |
| `PRODUCT_VISION.md` | Where the product is going, and for whom |
| `HARDWARE_PROPOSAL.md` | Owning capture end to end (Track C) |
| `PHASE6_VISION_PLAN.md` | The detector retrain; folds into MASTER_PLAN once it lands |

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

---

## Outcome — wave 1, 2026-08-20 (v1.26.0 through v1.30.1)

Executed as five parallel worktree agents. Tests 394 to 562; CI green on Python
3.13. Your match files were byte-identical throughout.

**Track A answered, and the answer was neither option offered.** The question was
"model or resolution?" It was resolution, but the binding limit was ours, not
YouTube's: inference downscaled every frame to 960 px. Same footage, same model:

| source | `imgsz` | ball | grade |
|---|---:|---:|---|
| 640x360 | 960 | 2.2% | unusable |
| 1920x1080 | 960 | 6.6% | unusable |
| 1920x1080 | 1920 | **38.3%** | **measured** |

The detector retrain that `PHASE6_VISION_PLAN.md` blocked on since June was never
the keystone. It is still wanted for jersey numbers and identity; it does not
unblock the ball.

**Track B mostly closed.** Three further defects in the spatial layer, all the
same family as the flank bug - a team-relative claim computed in an absolute
frame. Identity permanence went from zero tests to 27, with the fragmenting cause
characterised before anything was tuned. Still open: no calibration has run
against real match video, so `coordinate_space` has never read `pitch`.

**Track C unchanged.** Still needs a camera at height. `2ZKZwKKiCL8` in
`docs/FOOTAGE.md` is a genuinely fixed 4K amateur match - useful as a stand-in.

**Track D done.** Nine plans archived under `docs/archive/`.

### The new critical path

A `measured` grade does not yet produce measured possession. The `post` run
detects the ball in 38.3% of frames and still yields **0 passes and 0/0
possession** - every ball frame reads `loose`. Measured directly: the median
ball-to-nearest-player distance is 6.91 pseudo-metres and only 4.9% of ball
frames fall inside `possession_radius_m = 1.5`.

An uncalibrated run has no metres. `_project` maps image coordinates onto a
nominal 105x68 pitch whatever fraction of it is in frame, with no perspective
correction, so a metre-denominated threshold cannot mean the same thing in two
parts of the image. **Calibration now blocks possession and passing**, which
reverses the priority this plan opened with.

### Wave 2, in evidence order

1. Calibrate against real footage - `docs/SPATIAL_VALIDATION.md` has the procedure
2. Pitch-polygon filter on detections before `identities.update()` - two
   workstreams converged on this independently; it addresses identity churn and
   off-pitch projections at once
3. Make `vision/heuristics.py` thresholds calibration-aware
4. `vision/schema.py:player_token` - one player becomes several ids as team and
   jersey labels firm up
5. Re-benchmark at 4K on `2ZKZwKKiCL8`
