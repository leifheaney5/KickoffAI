# Spatial validation — what the pitch coordinates are known to be worth

Scope: `vision/analytics.py` (heatmaps, team shape, territory, average
positions, the analyst digest) and `vision/calibration.py` (picked points ->
homography -> metres). Tests: `tests/test_vision_analytics.py`,
`tests/test_calibration.py`. Fixture:
`tests/fixtures/tactical_camera_calibration.json`.

The short version: the maths is now covered, the wiring is now covered, and the
one thing still missing is the only one that needs a stadium. **No calibration
has ever run against real match video end to end. `coordinate_space` has never
once read `"pitch"` on a real match.** Everything below is written to keep that
sentence from quietly becoming untrue-by-assumption.

---

## 1. What is verified

### The calibration chain

Two independent camera geometries, both exercised through
`homography_from_calibration` and through `MatchAnalyzer._project`, which is the
single place a pixel becomes a pitch coordinate:

- **`SIDELINE`** — a symmetric trapezoid standing in for a sideline camera. Its
  symmetry gives a ground-truth-free check: every pixel on the centre column
  must land on the halfway line whatever its height.
- **The tactical fixture** — an exact pinhole projection of the ground plane
  from a stated camera pose (24 m up, 20 m behind the near touchline, level with
  the right-hand penalty box, no pan or roll, tilted down 36.87 degrees, focal
  1200 px, 1920x1080). The projection is computed in the test module by plain
  trigonometry with no OpenCV in it, so it is an independent oracle rather than
  a baseline captured from a run.

Established against the tactical fixture:

| Claim | Result |
|---|---|
| Four picked landmarks come back as themselves | exact to 1e-4 |
| Landmarks *not* given to the fit are recovered (penalty spot, D apex, both six-yard corners, goal centre) | exact to 1e-3 |
| The fit extrapolates across the halfway line it never saw | centre spot recovered to 1e-3 |
| A 2 px slip on one click | 0.15 m error in the box, 1.2 m at the centre spot, 6.3 m at the far corner |
| Image row halfway between the touchlines | pitch y = 1325/18 = 73.6, not 50 |
| Ten pixels of screen width | 0.652 m upfield, 0.259 m near the camera — 2.5x |
| Same frame, no calibration | centre spot lands 36 m along and 17 m across from where it is |

That last row is what calibration buys, stated in metres rather than as an
article of faith. The 2 px row measures how it is lost: accuracy is bought where
you calibrate and spent everywhere else, and the vertical component of a click
(which encodes depth) dominates. **A half-pitch calibration must not be trusted
at the far end of the pitch.**

### The analytics

Every expected value in `tests/test_vision_analytics.py` is computed by hand, so
the suite fails when the maths changes rather than when the output changes.
Covered: point collection and team resolution, the heatmap's bin order and
normalisation, average positions, per-frame and match-averaged team shape,
attack-relative territory, hotspot zone labelling, and the analyst digest.

Degenerate and hostile inputs now have tests: an empty run, a single tracked
player, a whole team stacked on one point (zero spread), a track seen once, a
missing y with x present, NaN, and a projection from beyond the horizon.

### Bugs found and fixed while writing these

1. **`--fixed-camera` was never applied.** Parsed, reported, and then the live
   runner built the analyzer with no homography. Calibration could not have
   taken effect even where it existed. (v1.24.0/v1.25.0)
2. **`_zone_label` mixed frames of reference.** Thirds flipped for a team
   attacking the other way but left/right stayed fixed to the frame, so one
   label combined a team-relative third with an absolute touchline and named the
   wrong wing for one of the two sides. (v1.24.0)
3. **"Higher average line" compared raw `centroid_x`.** A high line means far
   from your *own* goal; the two sides attack opposite ways, so for one of them
   a large x is the deepest position on the pitch. The digest named the deeper
   team as the higher one whenever the deeper side was the one attacking towards
   x=0. Same family as (2), one function further along.
4. **`team_shape_series` raised on a record with x but no y.** It checked only x
   and then read both. `collect_player_points` checked both. Two functions, two
   conventions, one `TypeError`.
5. **One off-pitch projection poisoned the whole match.** No filter existed
   because none was needed while every run was uncalibrated: image-space
   coordinates are pixels over the frame size and cannot leave 0..100. Under a
   homography a crowd or bench detection projects hundreds of pitch-lengths
   away, and a single one of those takes the centroid, the compactness and every
   average position with it. `usable_xy` now drops them, with a margin generous
   enough to keep a throw-in taker.

### The `collect_player_points` / `team_points` divergence — reconciled

`collect_player_points` (and so the formation dots) backfilled a track's team
onto its earlier unlabelled sightings; `team_points` (and so the heatmap)
filtered frame by frame and discarded them. The two panels were computed over
different point sets for any track whose colour was pinned down late.

Reconciled in favour of the track. A track is one player, so its team is a
property of the track, not of a frame — `vision/teams.py` already majority-votes
a track's colour history for exactly that reason, and `track_teams` now applies
the same convention at the document level. `collect_player_points`,
`team_points`, `team_shape_series` and `territory` all select on it, so the four
consumers cannot disagree.

Worth knowing: on today's pipeline output the divergence was **unreachable**.
`vision/schema.py:player_token` encodes the team letter into the player id
(`TeamX_trk7` -> `TeamA_trk7`), so a single id never carries two different team
labels and the backfill branch could never fire. The reconciliation was still
worth doing — it is now impossible for the two panels to disagree rather than
merely unlikely — but it fixed a latent inconsistency, not an observed wrong
number.

---

## 2. What is NOT verified

- **No end-to-end calibrated run against real match video.** Not once. Every
  `match_stats.json` this project has produced reports
  `coordinate_space: "image"`. The homography maths is correct and the runner
  now passes it through, but "correct in a test" and "correct on a Saturday
  morning" are different claims and only one of them is made here.
- **That any real camera matches the fixture's model.** The fixture is
  synthetic. It is a genuine perspective projection, not a plausible-looking
  trapezoid, but it assumes no pan, no roll, no lens distortion and a known
  pitch size. Real barrel distortion and a real pan are both absent from it.
- **That a user can pick four landmarks accurately enough.** The 2 px
  sensitivity test says what a slip costs; nothing says how big a real slip is.
- **Track fragmentation.** Because the team letter and the jersey number are
  both baked into the player id, one physical player becomes several ids over a
  run (`TeamX_trk7` -> `TeamA_trk7` -> `TeamA_No10`). `average_positions` shows
  them as separate dots and `min_frames` may drop each fragment. This is a
  schema/pipeline question, not an analytics one, and it is untouched here.
- **Third boundaries differ between modules.** `vision/analytics.py` cuts thirds
  at 33.333/66.667; `vision/bridge.py:pitch_zone` cuts them at 33/66. A player
  at x=66.5 is in the middle third on the Team Shape page and the attacking
  third in the event feed. Left alone deliberately — `bridge.py` belongs to
  another workstream — but it should be reconciled.

---

## 3. The real reference frame, and what could honestly be read off it

A LaLiga tactical-camera still (Real Madrid v Barcelona, 640x360 probe of a
1080p source, camera measured near-static at 0.22 px median shift) was inspected
while building the fixture. It shows the right-hand penalty area, the goal, the
centre circle and the halfway line.

Landmark reads, **eyeballed, not measured** — coordinates in the 640x360 probe,
multiply by 3 for the 1080p source:

| Landmark (`vcal.LANDMARKS` name) | Probe px | Confidence |
|---|---|---|
| Right box front x top | ~(411, 90.5) | +/- 1.5 px, corner clearly resolved |
| Right box front x bottom | ~(517, 210.5) | +/- 1.5 px, corner clearly resolved |
| Top-right corner | ~(484, 52.5) | +/- 2 px, sits against the boards |
| Halfway line x top touchline | ~(143, 76) | +/- 2 px |
| Centre spot | ~(150, 166) | +/- 3 px, *inferred from the circle's centre* — the spot itself is not distinguishable at this resolution |
| Bottom-right corner | — | **out of shot**; the goal line leaves the right edge of the frame before it reaches the near touchline |

Two things follow. First, +/- 2 px on a 640-wide probe is +/- 6 px at 1080p, and
the sensitivity test above says a 2 px error is already worth metres at the far
end — so these numbers are not good enough to derive known-answer expectations
from, which is why the checked-in fixture is synthetic and says so in its own
`source` field. Passing eyeballed guesses off as measurements would have meant
capturing expected values from a run, which is exactly what this suite exists
not to do.

Second, the usable landmarks on this frame cluster near the far touchline. Only
the centre spot and the near penalty-box corner carry any depth, so the quad is
poorly conditioned in the direction the perspective is most sensitive to. A real
calibration should either use a wider frame or accept that the near-touchline
half is the weak axis.

One encouraging observation: on this frame, lines of constant pitch width run
close to horizontal (the far penalty-box corner and the goal line's crossing of
the same 13.84 m line both sit near image row 90). The fixture's no-pan
simplification is therefore not wildly unlike this particular camera.

---

## 4. What would close the gap

In order. Each step is cheap and the sequence is the point — do not skip to 4.

1. **Calibrate a still.** Take a full-resolution frame from a fixed-camera clip,
   pick four `LANDMARKS` points in the app, save
   `pitch_calibration.json`.
2. **Check the calibration against markings the fit never saw.** Project the
   penalty spot, the six-yard box corners and the centre spot back through the
   homography and compare against their standard positions on the declared pitch
   size. This is `test_landmarks_it_was_not_calibrated_on_are_recovered` run by
   hand on real geometry, and it is the step that turns "the maths works" into
   "this camera is calibrated". Record the residual in metres.
3. **Run the pipeline with `--fixed-camera` and assert the obvious.**
   `match_stats.json` must report `coordinate_space: "pitch"`. If it says
   `"image"`, stop: the wiring has regressed and nothing downstream means
   anything.
4. **Sanity-check the output against the video.** Keeper inside his own box.
   Both teams' centroids in plausible halves at a goal kick. Nobody in the
   stands. Count how many points `usable_xy` drops — a nonzero count is expected
   and a large one is a detector problem, not an analytics one.
5. **Re-measure the numbers this document guesses at.** Real click error, real
   residual, real off-pitch rate. Then replace section 2's first bullet with a
   result, and add the run's frame as a second, genuinely measured fixture.

Until step 3 has been done and its output kept, the honest description of this
layer is: the geometry is right, the wiring is right, and it has never been
pointed at a pitch.
