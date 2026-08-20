# Changelog

All notable changes to **Kickoff Pulse** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versioning policy: roll the version on every commit, push, or merge.

- **patch** (`x.y.Z`) - fixes, docs, merge bookkeeping, small internal changes
- **minor** (`x.Y.0`) - backwards-compatible features and user-facing additions
- **major** (`X.0.0`) - stable baselines or breaking changes

The app version also lives in `build_app.sh` (`CFBundleShortVersionString` /
`CFBundleVersion`) and the Python package version lives in `vision.__version__`.
Both should stay in sync with the latest released version below.

Historical backfill note: earlier work did not maintain a changelog at the time
of each push, so the historical entries below are backfilled from the Git
history. Those entries include the source commit hash.

## [Unreleased]

- No unreleased changes.

## [1.24.0] - 2026-08-20

Validation plan Track B and Track D. The spatial half of the product had 305
lines and 16 functions with no tests, and had never once been fed calibrated
input; two real bugs were hiding in that gap.

### Fixed

- **`--fixed-camera` was parsed and reported but never applied.** The live runner
  built `MatchAnalyzer(cfg)` with no homography, so every live run reported
  `coordinate_space: image` however carefully the pitch had been calibrated. A
  missing calibration file was only half the reason the spatial layer had never
  run - the other half was that the runner could not have used one. It now loads
  the saved calibration, says so on stdout, and says so just as clearly when the
  flag is set with nothing saved or with a calibration it cannot use.
- **Flank labels were not attack-relative.** `_zone_label` flipped the thirds for
  a team attacking the other way but left `left`/`central`/`right` fixed to the
  frame, so a single label mixed a team-relative third with an absolute
  touchline. "Attacking third / left" named the wrong wing for one of the two
  teams, in the digest handed to the AI analyst.

### Added

- `tests/test_vision_analytics.py` - 34 known-answer tests over all 16 functions
  in `vision/analytics.py`. Expected values are computed by hand rather than
  captured from a run, so the suite fails when the maths changes rather than when
  the output changes. Covers heatmap axis order and out-of-range clipping, the
  min-frames noise floor, exact shape geometry, attack-relative territory, and
  the uncalibrated warning.
- `tests/test_calibration.py` - 15 tests over the picked-points to pitch-metres
  chain, against a sideline trapezoid whose correct output is derivable by hand.
  The strongest is the perspective invariant: the image centre column must map to
  pitch x=52.5 m at every image height, which an affine fit or a transposed
  matrix would break. Foreshortening is checked too - image mid-height maps to
  pitch 62.5, not 50; a linear stretch would look plausible on a heatmap while
  being wrong by 12 metres.
- CI installs `opencv-python-headless` so the homography maths is checked there
  rather than only on a dev box. The tests skip cleanly where OpenCV is absent.
- Documented divergence: `collect_player_points` backfills a track's team onto
  its earlier sightings while `team_points` filters frame by frame, so the
  formation dots and the heatmap are computed over different point sets for any
  track labelled late. Left as-is and pinned by a test rather than changed, since
  either behaviour is defensible.

### Changed

- Nine spent plan documents moved to `docs/archive/` with a README mapping each
  to the version that shipped it. Fourteen plans at the root had become hard to
  navigate and at least one contradicted another on sequencing; five stay live.
  Archived rather than deleted - they record why decisions were made, which
  outlives the plan.
- Test count 323 to 372.

### Still open

No calibration has yet been run against real video, so `coordinate_space` has
still never read `pitch` on a match. The path is now proven and tested; it needs
footage worth pointing it at - Track A (a 1080p Veo export) or Track C (a fixed
camera).

## [1.23.1] - 2026-08-19

Two defects found by running a real 99-minute match through the pipeline.

### Fixed

- **The batch path discarded everything on a transient network stall.** A
  YouTube source timed out four and a half minutes into a run
  (`IO error: Operation timed out`) and `analyzer.run()` simply stopped, writing
  no output — the stepping path has always reconnected there, the batch path
  never did. It now uses the same reconnect.
- **A YouTube VOD was being treated as a live source.** v1.20.0 keyed "live" off
  the source *kind*, so any network source got wall-clock timing. A VOD is read
  far faster than real time, which would have badly overstated the match clock.
  "Live" now means the source produces frames in real time: cameras, genuinely
  live streams, and plain network URLs (a Veo `.m3u8`, which cannot be told from
  a VOD and is the case where outage drift actually matters).

## [1.23.0] - 2026-08-19

Wire the producer side: the Ear and Manual Entry can now emit what the analytics
can measure.

### Fixed

- **The taxonomy shipped without anything producing it.** v1.22.0 grew the
  vocabulary to 44 actions and the analytics consumed it, but the parser prompt
  still listed the original 13 and never asked for body part or play pattern —
  so the app could measure far more than it could capture. A match run in that
  state would have produced exactly the same thin data as before.

### Changed

- **The parser prompt is generated from `football/taxonomy.py`** rather than
  duplicating a list, so the two can never drift apart again. It now asks for
  `body_part`, `play_pattern` and `big_chance`, and asks specifically for a
  shot's location — the single field that most improves the analysis, since it
  is what turns expected goals from a flat average into an estimate of the
  chance actually taken.
- **The prompt forbids guessing.** A fabricated body part would silently skew
  every xG built on it, so unstated fields must come back null.
- **Ingest canonicalises without destroying what was said.** `action` keeps the
  speaker's word for review; `action_canonical` and the qualifiers carry the
  taxonomy's form for analysis.
- **Manual Entry** reads its action list from the taxonomy (commonest first) and
  gains body part, play pattern, clear-cut-chance and a location picker.

Every qualifier remains optional. A coach who narrates plainly still logs
exactly the events they always did.

## [1.22.0] - 2026-08-19

Master plan Phase 2: the taxonomy, expected goals, and derived metrics.

### Added

- **`football/taxonomy.py`** — one place that says what an event *is*. The
  vocabulary grew from **13 actions to 44**, with optional qualifiers (body part,
  play pattern, shot outcome, big chance, under pressure) held as a flat mapping
  so a new qualifier never needs a schema migration. Synonyms collapse in tested
  code rather than in a prompt: a model says "shoots", "strike" and "effort" on
  different days and all three mean one thing. **Absent means unknown, never
  zero** — a coach who narrates plainly still gets exactly the stats they always
  got.

- **`models/xg.py` — expected goals, published rather than fitted.** A
  transparent geometric model whose every coefficient is written in the source,
  printed in the report, and open to argument. Labelled a *model*, never a
  measurement. Importing a professional xG surface would be confidently wrong on
  under-14s in a direction nobody could see; this one is meant to be refit
  against our own shots as volume grows.

  The first coefficients were **wrong and caught by testing**: they gave a
  central penalty-box shot 0.70 xG, a penalty-level number. Re-solved against
  published open-data baselines (~0.45 at six metres, 0.20 at eleven, 0.08 at the
  area edge), with the intercept lifted for youth goalkeeping. Those baselines
  are now pinned by tests. The `zone_14` centroid was also 23 m from goal when
  the penalty-area edge is 16.5 m.

- **`analytics/derived_metrics.py`** — PPDA with its numerator, denominator and
  zone all exposed, field tilt, final-third and box entries, and high turnovers.

- **Expected Goals and Possession Quality sections in the report**, each stating
  how far it can be trusted.

### Changed

- **Derived metrics refuse to report a number they cannot support.** Running
  against the real match log surfaced two ways of lying by arithmetic: PPDA of
  `0.0` from zero opponent passes reads as the most aggressive press ever
  recorded, and a field tilt of `100%` came from a single located event. Both now
  return nothing, with the reason given, below an evidence floor.

## [1.21.0] - 2026-08-19

Master plan: the coordinate bridge and the possession engine.

### Added

- **`football/zones.py` — the coordinate bridge.** Spatial analytics need x/y on
  every event; vision supplies them, the Ear does not. A logged event carries a
  free-text `location` — and in the real match log it is absent 217 times in 223.
  This maps a described place to a zone and a zone to its centroid, tagged
  `zone_estimate` so it is never presented as a measurement.

  It **refuses as carefully as it resolves**. The real log contains "utah, iowa"
  from a mis-transcription; inventing a pitch position for it would quietly
  corrupt every spatial metric above. Unrecognised phrases return nothing, and a
  partial description ("left wing" fixes the channel but not the third) stays
  marked partial rather than pretending to say more than it did. Vision-measured
  coordinates are never overwritten.

- **`football/possessions.py` — possession and sequence reconstruction.** Almost
  every metric worth having (PPDA, field tilt, sequence directness, possessions
  ending in a shot, high turnovers) is defined over possessions rather than
  events, so the engine is built before the metrics that need it.

  Deterministic by construction, and explicit about the edge cases where sloppy
  reconstruction invents or destroys possessions: a tackle hands the ball to the
  tackler, restarts are labelled as set pieces, unattributed narration joins the
  possession in progress rather than starting one, and a long silence ends a
  possession — a coach narrating live misses events, and a four-minute possession
  is fiction. Sequences split at restarts, since directness measured across a
  throw-in is meaningless. Classification thresholds are arguments, not magic
  numbers.

- **A Possession Quality section in the report** — possessions, share ending in a
  shot, passes each, and how many began from a set piece. Raw possession says who
  held the ball; this says what they did with it. Runs on a voice-logged match
  today and sharpens as vision adds events.

## [1.20.0] - 2026-08-19

Master plan Phase 0 and Phase 1. Plan: `MASTER_PLAN.md`.

### Fixed

- **Event timestamps drifted by the length of every stream outage.**
  `t_sec = _raw_index / fps` counted frames *received*, not time *elapsed*, so a
  60-second dropout stamped everything after it 60 seconds early and the error
  compounded per reconnect. It propagated through `bridge.py` into wall-clock
  stamps, which **cut clips in the wrong place**. Live sources now take time from
  the wall clock; files keep frame-based video time, which is correct there and
  has no outages. Half-time is excluded via `note_paused()`, so a break does not
  read as forty-five minutes of play.
- **A live run left no footage.** Only `match_stats.json` was written, so a live
  match produced numbers and nothing to clip, review, or annotate for the
  retrain. `--record` now tees the incoming stream to disk in a separate ffmpeg
  process — a stream copy, so no re-encode and full frame rate — and the
  supervisor turns it on by default. A crash in analysis cannot cost the
  footage. Webcams decline cleanly (a camera device cannot be opened twice).

### Added

- **`analytics/` — the metric registry and query engine.** Metrics are
  compositions of filters over events, declared once and evaluated generically,
  rather than hand-written functions. `EventQuery` composes action, result, team,
  player, source, half, minute, thirds, channels, box entry, pressure,
  progression and coordinate provenance; `Metric` declares meaning, aggregation,
  units, version and confidence.
- **The existing sixteen stats migrated onto it**, and asserted to reproduce
  `stats.py` exactly on real match data. That migration caught a real design
  error before it shipped: the query defaulted to requiring `status="approved"`,
  but events arrive `pending` and count until denied — every live match would
  have shown zeros.
- **Coordinate provenance** (`measured` / `projected` / `zone_estimate` /
  `unknown`), with a metric reporting the **weakest** provenance behind it. A
  mean over nine measurements and one zone estimate is not a measurement.
- **A machine-readable catalogue**, per-90 that refuses meaningless samples, and
  clip anchors on every result — the events behind a number, so a claim can be
  watched rather than believed.
- `feed.record_live` and `feed.fixed_camera` in `control.json`.

## [1.19.0] - 2026-08-19

Own the capture. Proposal: `HARDWARE_PROPOSAL.md`.

### Added

- **`scripts/rig_capture.py`** — the capture agent for our own camera rig.
  Records to local storage **first** and streams second, which is the whole
  reliability argument: if the wifi drops or the laptop dies, the footage is
  still on the rig's SSD. One encode, two sinks via ffmpeg `tee`, with the file
  listed first so a failing stream muxer cannot take the recording with it.
  Pi-oriented but not Pi-specific — it drives ffmpeg, so a laptop webcam works
  for testing.
- **`feed.fixed_camera`** — a declaration that the camera does not pan, surfaced
  on Camera & Feed and carried into every run's `run_quality`.

### Changed

- **The trust gate now knows the difference between a fixed and a panning
  camera.** A homography maps pixels to metres only while the camera stays
  still, so on an auto-following camera a saved calibration is stale the moment
  play moves. `quality.assess()` previously treated "calibrated" as good news
  unconditionally; it now names the trap — *calibrated, but the camera pans, so
  treat positions as image-space anyway*. This is the same fact the repo has
  recorded in four places (`ROADMAP.md`, `NEXT_STEPS.md`) without the app ever
  acting on it.

### Notes

The hardware case is not primarily about cost. Veo's auto-following camera is
the single largest obstacle to spatial analysis here: it invalidates calibration
continuously and fragments tracks into ~75 identities for ~22 players. A fixed
mount fixes all of that on day one with no model work — and owning the storage
supplies the 1080p footage the retrain has been blocked on since June. Both
roadmap keystones, cleared by one weekend of Stage 0.

## [1.18.0] - 2026-08-19

Clips, player development, and share packs — the moment, the trend, and a way to
hand both to the player. Plan: `FEATURES_PLAN.md`.

### Added

- **`clips.py` — automatic match clips.** Cuts goals, cards, shots on target and
  saves out of the match video with ffmpeg. Nobody watches a 90-minute match
  video; everybody watches the goal.

  Alignment is by **wall clock**, not the match clock. Mapping match time onto
  video time breaks at the interval — the match clock stops at 45:00 while the
  video keeps rolling — so a second-half event lands minutes early. Measured on
  a worked example: an event at match 50:00 sits at video 70:00, a 20-minute
  error. `video_position = event_timestamp - recording_started_at` removes the
  problem outright. Videos the app recorded align automatically; for anything
  else the anchor is derived from one moment the user can point at ("the first
  goal is at 12:30"), since nobody knows when a recording began.

  Goals get a longer window than cards (build-up matters for one, not the
  other), events outside the video are flagged rather than cut, and a plan is
  shown before anything runs so a bad anchor is obvious before ffmpeg spends
  minutes on it.
- **Player development.** `season.player_season()`, `player_form()` and
  `squad_involvement()`, with a Players view on the Season page. Season counted
  goals and nothing else, yet every mirrored event has carried a `player` since
  the first release — the data was there and simply never read. Form compares a
  player to **their own** baseline, never to the squad: in a youth team the
  spread between players says more about age and position than about progress.
  Squad involvement shows appearances least-used first, since many youth leagues
  expect roughly equal playing time and nothing made that visible.
- **`player_pack.py` — per-player share packs.** A portrait card plus that
  player's clips and season trend, as a zip a parent will open. Scoped to one
  player: no squad table, no other children's names. The card's height follows
  its content — a fixed portrait sized for a six-stat forward left a defender
  with two tackles looking like a broken layout.

### Notes

Deliberately no new spatial analytics. Ball detection still grades most runs
*indicative* (`quality.py`), so shape-over-time or positional patterns would ship
caveated and teach coaches to distrust the numbers. These three features run on
the event log and the video file, both reliable today.

## [1.17.0] - 2026-08-19

The touchline release: watch a live match from a phone. Plan:
`UX_ARCHITECTURE_PLAN.md` (B3, B4, C).

### Added

- **Sideline view (C)** — a read-only page sized for a phone: scoreboard, the
  Eye's latest frame, and recent events. `KICKOFF_LAN=1` binds Streamlit to the
  local network (it was localhost-only) and the launcher prints the URL and an
  access code. Nothing on the page writes, so a phone can never disturb a live
  capture.
- **Sideline access control.** Club accounts win where they are in use — a
  signed-in user needs no code. Without accounts, LAN mode requires a shared
  code, generated per launch if none is set. Binding to the network was already
  opt-in, but "anyone on the wifi can watch the match" should be a decision, not
  a surprise. Verified that no match content renders before the code is
  supplied.

### Changed

- **Responsive layout (B3).** The scoreboard hard-coded a 68px score and a 200px
  centre column, which is what broke narrow screens. Layout-critical sizes are
  now tokens (`--sb-score`, `--sb-clock`, `--sb-center`, `--chip-min`), so the
  tablet and phone breakpoints retune the whole design by redefining a handful of
  variables instead of overriding rules one at a time. `brand.py` previously had
  three `@media` rules in ~500 lines.
- **Sidebar rule (B4).** Account and the new Sideline view sit in a "You" group —
  identity and remote viewing are not match-day workflow steps, and padding an
  existing group with them would have blurred what those groups mean. The rule is
  written down next to the nav: about four entries per group, and a group earns
  its place by mapping to a distinct moment in the match day.

## [1.16.0] - 2026-08-19

Artifacts reach the club library, destructive actions ask first, and the flows
themselves are tested. Plan: `UX_ARCHITECTURE_PLAN.md` (A3, B1 completion, D1, D3).

### Added

- **Media sync (D1).** `sync.py` pushed matches and events but not the *files*,
  so a club library held every number and none of the documents — nobody would
  notice until the first coach tried to open a colleague's report. Artifacts now
  copy to `KICKOFF_SHARED_LIBRARY_ROOT` (the same relative paths work on both
  sides, so nothing is rewritten). Reports, stats and CSVs always travel; video,
  images and voice notes stay local unless `KICKOFF_SYNC_VIDEO=1`, and any single
  file over `KICKOFF_SYNC_MEDIA_MAX_MB` is skipped so one huge upload cannot
  stall an otherwise good sync. Media copies **after** the match row commits and
  never rolls it back — club wifi will interrupt a 2 GB video, and losing the
  match record over that would be absurd. Skips are reported with their reason
  rather than silently dropped.
- **`ui_helpers.confirm_action()` (A3)** — a two-step guard applied by
  consequence. Resetting a running match clock, deleting gigabytes of
  recordings, and discarding a pitch calibration were each a single unguarded
  click; all three now say what will be lost. `Undo last event` is trivially
  redone and deliberately stays one click.
- **`tests/test_flows.py` (D3)** — seven end-to-end flows across module
  boundaries: first run to readiness, match → archive → next match, capture →
  sync → another user's view, an interrupted sync resuming, and a camera run
  reaching the report, library and season. Page tests only assert "renders";
  the UUID bug that broke archiving for every club install passed every unit
  test and only fell out of a full flow.

### Changed

- **All 15 pages now really do open the same way.** v1.15.0 migrated the seven
  legacy pages but left the other eight calling `brand.app_css()` and
  `brand.page_header()` by hand — the split it set out to remove was still half
  present. Every page now calls `UI.page_setup()` and nothing else.
- The match-clock Reset is guarded only when a clock exists to lose, so a stray
  click before kickoff still costs nothing.

## [1.15.0] - 2026-08-19

First-run guidance, a visible match lifecycle, and one page convention. Plan:
`UX_ARCHITECTURE_PLAN.md` (workstreams A1, A2, B1, B2).

### Added

- **A "Get started" panel** on the Match Console, driven by
  `control.setup_state()` — a pure, testable resolver of what is ready and what
  is not. It lists only what is outstanding, marks which steps actually block a
  match, and names the page that fixes each. It disappears once you are ready,
  so it guides a new coach without nagging a returning one. The Match Console
  previously had *zero* empty-state handling: a new user landed on a 0-0
  scoreboard reading "Home" vs "Away" with nothing to tell them what to do.
- **A match lifecycle chip** in the status bar: Not started / Live / Half time /
  Finished / Archived, plus whether an archived match has reached the club
  library. `match_id`, `archived_at` and `sync_state` all existed but surfaced on
  one page, so "did my match upload?" could only be answered by navigating to
  Account. The club lookup is cached (15s) so a once-a-second status bar does not
  query the database sixty times a minute.
- `ui_helpers.page_setup()` — the single opening every page now uses.

### Changed

- **Every page now opens the same way.** Seven pages still called
  `st.set_page_config` (illegal under `st.navigation`, tolerated only by luck),
  eight did not; seven inserted the repo root into `sys.path`, eight did not; the
  CSS entry point was `global_css()` on half and `app_css()` on the other half.
  All fifteen now call `UI.page_setup()` and nothing else. Running a page
  directly is no longer supported — the router owns page config, navigation and
  the club auth gate, so a direct run would bypass all three.
- The two ad-hoc column-gap overrides pasted into page bodies are now a
  documented `page_setup(row_gap=...)` argument, so the same global selector is
  no longer redefined in two places with different values and no explanation.
- Empty-state copy corrected across Timeline, Insights, Team Shape and Match
  Library: they pointed at "the dashboard" and a "Video Analysis" page that has
  not existed since v1.12.0.
- `setup_state()` lives in `control.py`, not `ui_helpers.py` — it is pure logic
  and belongs somewhere CI can import without Streamlit.

## [1.14.0] - 2026-08-19

Club mode: several coaches, one shared library — plus the correctness fix that
made it possible. Plan: `CLUB_PLAN.md`.

### Fixed

- **Consecutive matches silently merged into one log.** Nothing ever cleared the
  working files: `finalize_match()` archived to the library and `archive=True`
  only *copied* `match_data.json`, so a second match appended to the first. The
  working log in this repo held two separate days of football. Matches now carry
  a `match_id`, and **Post-Match → Start new match** clears the event log, notes
  and camera stats, guarded against discarding anything unarchived.
- Writing a match owner raised on flush — user ids cross JSON as strings while
  the column is UUID-typed. `auth.as_uuid()` now guards every id write. Caught by
  an end-to-end club test, not by unit tests.

### Added

- **`auth.py`** — opt-in sign-in for a shared install. Passwords are PBKDF2-
  HMAC-SHA256 with a per-user salt at 600k iterations; session tokens are 256-bit
  and stored only as a SHA-256 fingerprint, so reading the session file does not
  yield a usable session (file mode 0600). Unknown users cost exactly one PBKDF2
  verify, matching a wrong password, so login cannot be used to enumerate
  accounts. **With no accounts defined the app is unrestricted** — a single-coach
  install never sees a login screen.
- **`users`, `teams`, `team_members`** plus `matches.owner_id` / `team_id`. The
  library and season are scoped to what the signed-in user may see; matches
  archived before club mode stay visible to everyone rather than vanishing.
- **`sync.py`** — offline-tolerant push of local matches to the club server.
  Capture never depends on the network: matches archive locally and push when
  reachable. Idempotent by `capture_id`, so a retry over a flaky connection can
  never duplicate a match; colliding slugs are disambiguated, not dropped.
- **Account page** — sign in, change password, manage people and teams, and run
  club sync, with the server URL shown password-redacted.
- **Recordings retention** (`prune_recordings`, `disk_usage`). Recordings had
  grown to 6.2 GB with nothing ever deleting them, and a full disk ends a live
  capture. Surfaced on Voice Backup with a free-space warning.
- **`requirements.lock`** pinning the verified environment, so a match-day
  rebuild cannot pick up a breaking upstream release.
- **`tests/test_control.py`** (20 tests) over the match clock, persistence,
  corrupt-file fallback and the match lifecycle — `control.py` was the most
  safety-critical untested module in the repo. Plus `tests/test_club.py` (28)
  covering the auth and sync properties above.

### Changed

- Postgres credentials and bind address are environment-driven
  (`KICKOFF_PG_USER` / `KICKOFF_PG_PASSWORD` / `KICKOFF_PG_BIND`). The port stays
  localhost-only by default; serving a club LAN now requires deliberately
  setting both, and the README says so.
- `finalize_match()` marks the match archived and records its `capture_id`, so
  starting a new match is safe and a later sync is idempotent.

## [1.13.0] - 2026-08-19

Vision/audio fusion behind an honest trust gate. The Eye's numbers now reach the
report, the momentum curve, the library and season analytics — but every run is
graded first, so a low-confidence run is labelled rather than believed. Plan:
`E2E_DEVELOPMENT_PLAN.md` (phases A, B, E, F).

### Added

- **`quality.py` — the trust gate.** Grades every camera run **measured /
  indicative / unusable** from its ball-detection rate, frame count, reconnects
  and calibration, and explains the grade in plain language. Thresholds live in
  one place so the retrain can retune every consumer at once. Pure functions, no
  vision deps, so it runs in CI.
- **`run_quality` block in `match_stats.json`.** The runner records frames, ball
  rate, fps, reconnects, paused time, calibration, model, device and source
  resolution. A report generated days later can still say how the run went;
  previously those figures were visible live and then lost.
- **Camera Analysis section in the report** (PDF + text): the run's reliability
  grade, the reasons behind it, and camera possession shown **beside** the
  play-by-play figures — never blended into them. When the two disagree by 15
  points or more the report says so and explains why the methods differ.
- **Vision in the momentum curve**, weighted by run quality (`measured` 1.0,
  `indicative` 0.4, `unusable` 0.0), so a poor run nudges the line instead of
  driving it. The Insights page shows the grade and the weight in force.
- **Fused key moments.** `insights.vision_pressure()` finds passages where the
  camera saw one side stringing passes together, and `key_moments()` now tags
  each moment `audio` / `momentum` / `vision` plus `confirmed` — true when a
  *different* ingest independently flagged the same team nearby. Agreement
  between the ear and the eye is the one signal neither stream can produce alone.
- **Season camera analytics.** `season.possession_trend()` and
  `season.vision_coverage()`, surfaced on the Season page. Only **measured** runs
  enter the trend: an indicative run is fine on its own match report, but its
  error is systematic, so averaging it into a season line corrupts the line.
- **Camera digest on the match row.** `matches` gained `vision_verdict`,
  `vision_ball_rate`, `vision_home_possession`, `vision_away_possession` and
  `vision_passes`, so season trends query the DB instead of opening a
  multi-megabyte JSON per match. Applied idempotently to existing databases.

### Changed

- **Checkpoint cadence split.** Serialising the per-frame tracking data measured
  **9.5 MB and ~247 ms** at the runner's 4000-frame bound — a stall on the
  capture loop that dropped frames every 10 seconds, ~5.0 GB of writes and 2.5%
  of wall clock over a 90-minute match. The cheap dashboard bridge stays on the
  10s cadence; the full document is written every 60s (`--full-interval`), at
  half-time, and always on exit. `MatchStats.stats_dict()` builds just the cheap
  half for callers that never needed the frames.
- **`events.source` is preserved into the library.** `vision/bridge.py` has
  always tagged camera events, but `finalize.py` dropped the field when mirroring
  to Postgres, so an archived match could not tell the Eye from the mic — which
  made cross-match vision analysis impossible. Existing rows backfill to `audio`.
- `vision/NEXT_STEPS.md` and `vision/ROADMAP.md` corrected: 4-point pitch
  calibration is built (it shipped in v1.12.0 and lives on Camera & Feed), the
  hardcoded-CPU note is obsolete, and the page names match reality.

### Fixed

- **`analyzer.close()` silently overwrote the runner's final checkpoint.** It
  re-saved a document without the `run_quality` block over the one the runner had
  just written, so run quality never survived a session. `close(save=False)` lets
  a caller that maintains a richer document write it itself.
- The momentum renderer now logs when it falls back from matplotlib to Pillow,
  so a report whose chart looks unfamiliar is explainable.
- `quality.assess()` no longer reports "uncalibrated camera" when no camera run
  happened at all.

## [1.12.1] - 2026-08-17

### Fixed

- Report momentum chart export now falls back to Pillow when `matplotlib` is
  not installed, so lean installs and CI still generate the expected artifact.
- The Eye supervisor now reports a missing feed before checking optional vision
  dependencies, keeping Camera & Feed setup validation clear on CI and fresh
  installs.

## [1.12.0] - 2026-08-17

Vision-first ingest. The camera feed becomes the primary way to capture a match
and voice becomes an explicit backup lane, with the navigation reorganised around
the match-day lifecycle. Plan: `UI_INGEST_PLAN.md`.

### Added

- **`vision_runner.py`** — supervises the persistent vision runner (the Eye) from
  the app: `start` / `stop` / `pause` / `resume` / `status` / `reconcile`, over a
  `vision_runner.json` state file with PID liveness checks, mirroring
  `screen_recorder.py`. The Eye can now be started and stopped from the UI; it
  previously required pasting a `scripts/live_vision.py` command into a terminal.
- **`pages/Camera_and_Feed.py`** — the new front door for ingest: feed source
  (Veo stream / webcam / file), a **Test connection** button that grabs one frame
  and reports its resolution, model and device settings, pitch calibration
  promoted to a first-class section, and the ingest-mode switch.
- **`ingest_mode` and `feed` in `control.json`** — one persisted source of truth
  for the feed, read by the app, the launcher and the runner. Old control files
  merge cleanly with no migration.
- **`vision/runtime.py`** — shared device selection (`best_device`,
  `resolve_device`) and live pipeline config, so the page, the runner and the
  supervisor build identical pipelines.
- **`vision/render.py`** — shared drawing (annotated frames, tactical map with
  its overlay layers, passing map), replacing the near-duplicate `annotate` the
  live runner carried.
- **Runner health file** (`live_eye_status.json`) — the Eye publishes frames,
  fps, ball-detection rate, possession, passes and match time roughly once a
  second, so the app's chips read a tiny file instead of re-parsing the
  multi-megabyte `match_stats.json`.
- **Ingest-aware status chips** — the status bar now shows the Eye's health,
  fps, ball rate, possession and passes, and only renders the voice chips when
  the match uses the mic.
- **Written match notes.** A **Match notes** section on the Match Console with a
  proper composer: type a note, and it is stamped with the match clock and saved
  alongside spoken notes in `notes.json` — so it flows into the post-match report
  and the library archive identically. The section always renders, whatever the
  ingest mode; previously notes were reachable only by speaking, which left a
  vision-only match with no way to record an observation at all. When voice is
  on, Write / Speak sit in tabs. Notes now carry a `source` field and are tagged
  **WRITTEN** or **VOICE** on the console and on Insights (legacy notes, which
  all came from the mic, read as voice).

### Changed

- **Navigation reorganised** to Set up → Live → Analysis → After match, with the
  visual path leading each group. The Match Console is the default page. Page
  files lost their numeric prefixes (`pages/4_Video_Analysis.py` →
  `pages/Film_Room.py`, `pages/Audio_and_Mic.py` → `pages/Voice_Backup.py`,
  `pages/Live_Match.py` → `pages/Match_Console.py`, and so on).
- **Match Console rebuilt vision-first**: the Eye's live frame and controls sit
  under the scoreboard, one transport drives the clock and every configured
  ingest, **Half** idles the Eye without losing stats, and the voice sections
  render only when the match uses voice.
- **Voice demoted to a backup lane**: `kickoff.sh`, `kickoff.ps1` and
  `desktop.py` start the audio tracker only when `ingest_mode` includes voice.
  Voice remains fully functional — this changes defaults and framing, not
  capability. Override with `KICKOFF_INGEST=both`.
- **Film Room** (was Video Analysis) handles recorded files only, 965 → 401
  lines. Its live stepping loop is gone: a live run belongs to the persistent
  runner, which survives navigation, where the page's loop died the moment you
  clicked away.
- `launch-app`, `app-doctor` and `analyze-video` skills updated for the vision
  path, ingest modes, and runner triage.

### Fixed

- **Stopping the Eye no longer blocks the UI for 20 seconds.** `stop()` waited on
  process exit, but the runner spends that time tearing down torch's MPS context
  *after* its final checkpoint has already landed. It now waits on the runner's
  PID file — removed immediately after the checkpoint — and returns in ~0.1s,
  reporting `checkpoint_saved` so an unconfirmed save is never silent.
- **The Eye no longer looks dead while it is working.** Runner health was only
  published at 10-second checkpoints, so the app showed "starting" for the first
  frames of every run; status is now published about once a second, from before
  the first frame.
- A camera index reaching the runner as a digit string was resolved as a *file
  path*; webcams now pass through a dedicated `--camera` flag.
- A stale `.live_eye_paused` flag from a previous match no longer idles a newly
  started run.

## [1.11.0] - 2026-06-26

### Changed

- Merged the post-match report upgrades, the report-generation skills, and the
  CV uncalibrated possession tuning flags into `main`. The `analyze-video` skill
  is now functional on `main` (the `--possession-radius` / `--possession-frames`
  flags are present).

### Fixed

- The visual-timeline image is generated again as a standalone artifact (still
  archived into the match library and offered as a download); it was removed in
  1.10.1 from the report PDF only, which inadvertently dropped it from the
  library archive too.

## [1.10.1] - 2026-06-25

### Changed

- Report files are now named by teams + match date (e.g.
  `Hub_City_FC_vs_Ristozi_FC_2026-06-24.pdf`) instead of a generation
  timestamp, for intuitive lookup.

### Removed

- Further trimmed the report: removed the Key Moments, Substitutions, and
  Visual Timeline sections.

## [1.10.0] - 2026-06-25

### Changed

- Redesigned the PDF report into a polished, coach-facing document: brand header
  with a smaller logo + "POST-MATCH REPORT" title, navy section accent bars,
  bordered cards, alternating shaded stat tables, a consistent colour scheme, and
  a footer with page numbers + contact email.
- **By Half** is reformatted into a grouped table (1st/2nd half, each with Home
  and Away columns in team colours) instead of the hard-to-read `H-A` cells.
- Reports now export to a tracked **`exports/`** directory by default
  (`REPORTS_DIR`), replacing the git-ignored `reports/`.

### Added

- **Team crests** in the scoreline band: drop `home.*` / `away.*` into
  `branding/teams/` (or pass `home_logo`/`away_logo` to `report.generate`).
- Contact email in the report header and footer.

### Removed

- Trimmed the report to the coach-relevant essentials: removed the Scoring
  Summary, Player of the Match, Vision Analysis (CV), Player Stats table, and
  textual Event Timeline sections (the CSV exports still carry the full detail).

## [1.9.0] - 2026-06-25

### Added

- Comprehensive coach report: the post-match report now embeds a **momentum
  graph** (new `momentum_image.py`, an area chart of `insights.momentum_series`
  with goals marked), an auto-tagged **Key Moments** timeline
  (`insights.key_moments` — goals, cards, shots on target, and sustained-pressure
  momentum swings), and an optional **Vision Analysis (CV)** section
  (`report.load_cv_stats`) summarising CV possession, passing, ball-detection and
  coverage. All embedded in both the text and PDF reports.
- `report.generate` accepts `cv_stats_file` to fold a vision `match_stats` JSON
  into the report; the CV section is clearly labelled as uncalibrated /
  image-space / partial-coverage so it reads as directional, not exact.

## [1.8.0] - 2026-06-24

### Added

- Post-match report now includes a **scoring summary** (goalscorers with the
  minute, denied goals excluded), an auto-selected **Player of the Match**
  (heuristic from goals, shots on target, saves, tackles, minus cards), and a
  **per-half breakdown** of the key stats (goals, shots, on target, corners,
  fouls). All three appear in both the plain-text and PDF reports.
- New shared helpers `stats.event_half` and `stats.team_stats_by_half` derive
  first/second-half splits from the stamped match clock.

### Changed

- Possession in the report is now labelled "(est.)" to make clear it is
  approximated from on-ball action share rather than measured.
- The opaque "momentum strength" number is replaced with a plain-language note
  ("Home/Away finished the stronger side").

## [1.7.0] - 2026-06-24

### Changed

- Audio ingest now runs capture and processing on separate threads. A bounded
  hand-off queue (`KICKOFF_AUDIO_QUEUE_MAX`, default 8) lets the microphone keep
  recording while Whisper transcription and Ollama parsing run, so fast
  back-to-back play-by-play is no longer dropped while a prior phrase is still
  being processed. When the worker falls behind, the oldest queued clip is
  dropped rather than blocking capture.
- Transcription now runs in memory: captured audio is converted to a 16 kHz mono
  float32 array and fed straight to Whisper, removing the per-phrase temp-WAV
  write/read/unlink (falls back to a temp WAV if numpy is unavailable).

### Added

- Live status now reports `queued` and `dropped` clip counts; the dashboard
  status bar shows a "Backlog" chip only when the worker is behind.
- Microphone error state is surfaced in `status.json` (`mic_error`).

## [1.6.0] - 2026-06-24

### Added

- Duplicate-event suppression in the audio loop: an identical event
  (same action/team/player) repeated within `KICKOFF_DEDUPE_SEC` (default 6 s)
  is dropped and kept as a reviewable record, so "goal, goal!" logs once.
- Microphone auto-recovery: after repeated read errors the tracker re-resolves
  `KICKOFF_MIC` and re-opens the device, so a dropped/reconnected input
  (e.g. AirPods) resumes without a restart.
- Substring-aware hallucination filter that catches boilerplate wrapped in extra
  words (e.g. "thanks for watching so much"), not just exact-match fillers.
- Benchmark now reports transcription vs parse latency separately and a
  word-level WER alongside the character-ratio scores.

### Changed

- Ollama parse timeout is now configurable via `OLLAMA_TIMEOUT` and defaults to
  15 s (was a hard-coded 60 s) so a hung model fails fast to the local keyword
  fallback instead of freezing capture.
- Learned corrections are cached and re-read only when `corrections.json`
  changes, removing per-transcript disk I/O from the hot loop.

## [1.5.0] - 2026-06-24

### Added

- Audio ingest review sidecars (`audio_reviews.json`, `review_audio/`) so each
  captured phrase can keep its raw transcript, corrected transcript, audio clip,
  parser source, latency, and linked event metadata.
- Timeline "Did you mean..." review prompts for pending voice events, including
  audio playback and learned correction capture from approvals or edits.
- Local learned corrections (`corrections.json`) applied after built-in soccer
  fixes and before spoken-number normalization.
- Audio chunking controls, a quick-commentary preset, and mic calibration/test
  phrase feedback in the Audio & Mic setup flow.
- `audio_benchmark.py` for repeatable WAV-based ingest benchmarks with starter
  phrase manifests.

### Changed

- Defaulted Whisper transcription to the medium English model for better short
  soccer-command accuracy.
- Ignored local audio review artifacts so deployments do not include runtime
  clips or transcript sidecars.

## [1.4.0] - 2026-06-24

### Changed

- Restructured the app around grouped, lifecycle-ordered navigation
  (`st.navigation`): **Live → Set up → Analysis → After match**. The home page is
  no longer a single long scroll.
- Split the old monolithic home page into focused screens:
  - **Live Match** (`pages/Live_Match.py`) - the match console: hero scoreboard,
    status chips, transport controls, real-time feed + stats, and thought notes.
  - **Match Setup** (`pages/Match_Setup.py`) - match details, team names/lineups,
    and the numbered roster + formation editor (previously crammed into the
    sidebar and the bottom of the home page).
  - **Audio & Mic** (`pages/Audio_and_Mic.py`) - background block-out, audio
    chunking, mic calibration, the voice guide, and screen capture.
  - **Post-Match** (`pages/Post_Match.py`) - summary + AI draft, player
    spotlight, report/data export, archive to library, and the share card.
- `dashboard.py` is now a thin router that sets up the design system and defines
  the grouped navigation; it no longer renders the home screen itself.

### Added

- `ui_helpers.py` - shared render/format helpers (scoreboard, status chips,
  stats feed, mic calibration, AI summary, etc.) used across the new pages.

## [1.3.0] - 2026-06-24

### Added

- Fixed-camera pitch calibration (Phase 2) for the video analysis page. For a
  non-panning camera (e.g. a Veo feed) the image-to-pitch homography is set once:
  grab a frame from the current source, click four known pitch landmarks, and
  every position projects into true pitch coordinates. New `vision/calibration.py`
  persists the correspondences (`pitch_calibration.json`) and rebuilds a static
  `PitchHomography`; a "Use fixed-camera calibration" toggle wires it into both
  the file and live analysis paths, overriding per-frame pitch detection. Adds
  the `streamlit-image-coordinates` dependency for click-to-mark.

## [1.2.0] - 2026-06-24

### Added

- Live-stream resilience for the video analysis pipeline: a stalled or dropped
  network feed (e.g. a live Veo HLS `.m3u8`) now reconnects from the live edge
  instead of ending the session. Adds FFmpeg reconnect/timeout capture options,
  a low-latency capture buffer, and config knobs (`live_reconnect`,
  `live_reconnect_attempts`, `live_reconnect_backoff`, `live_max_reconnects`,
  `ffmpeg_capture_options`). The live view reports recovered stream drops.

### Fixed

- YouTube URL resolution now uses the android/ios player client so the resolved
  media opens in OpenCV instead of failing with HTTP 403 (web-client URLs are
  bound to a browser session). High-res YouTube remains gated by Google's
  PO-token enforcement; a direct HLS feed (Veo) is the recommended source.

## [1.1.1] - 2026-06-24

- Backfilled prior commits and pushed merges into this changelog with SemVer
  entries.
- Synced app/package version metadata to `1.1.1`.

## [1.1.0] - 2026-06-24

- Added YouTube live/watch URL and direct stream URL support for video analysis.
  Commit `7dd4310`.

## [1.0.0] - 2026-06-24

- Merged Path A: webcam record-to-file analysis as the first stable baseline.
  Commit `bb71a0f`.

## [0.39.0] - 2026-06-24

- Added Path A: record a match from a webcam, then analyse the recorded file.
  Commit `0ea228e`.

## [0.38.2] - 2026-06-24

- Synced the Path A branch with `main` before merge. Commit `0d27d2b`.

## [0.38.1] - 2026-06-22

- Merged dashboard loading splash. Commit `8b16ee5`.

## [0.38.0] - 2026-06-22

- Added dashboard loading splash. Commit `9f83576`.

## [0.37.2] - 2026-06-22

- Hardened screen recorder startup. Commit `994ec69`.

## [0.37.1] - 2026-06-22

- Merged live webcam video analysis. Commit `5912ccd`.

## [0.37.0] - 2026-06-22

- Added live webcam video analysis and hardened the desktop launcher.
  Commit `b851d47`.

## [0.36.1] - 2026-06-22

- Merged native macOS desktop app wrapper. Commit `c70ed94`.

## [0.36.0] - 2026-06-22

- Added native macOS desktop app wrapper. Commit `667078f`.

## [0.35.1] - 2026-06-22

- Merged bulk zip and export backup. Commit `da7d3fd`.

## [0.35.0] - 2026-06-22

- Added bulk "Zip & export" backup for all or selected matches.
  Commit `97848fc`.

## [0.34.1] - 2026-06-22

- Merged Phase 6 plan, demo seeder, and PDF Unicode fix. Commit `7ff1cb5`.

## [0.34.0] - 2026-06-22

- Added Phase 6 vision plan and demo seeder; fixed PDF Unicode crash.
  Commit `92f9397`.

## [0.33.1] - 2026-06-22

- Merged one-button screen and mic recording. Commit `b0f7565`.

## [0.33.0] - 2026-06-22

- Added one-button screen and mic recording. Commit `de43bf5`.

## [0.32.0] - 2026-06-22

- Added tactical map thirds, team shape, average position, space control, ball
  trail, and passing lanes. Commit `e7fddd3`.

## [0.31.1] - 2026-06-22

- Merged tactical map zone and half-space overlay layers. Commit `e72818d`.

## [0.31.0] - 2026-06-22

- Added toggleable tactical map zone and half-space overlay layers.
  Commit `5d83dbd`.

## [0.30.1] - 2026-06-22

- Merged library-wide AI analyst. Commit `888e155`.

## [0.30.0] - 2026-06-22

- Added library-wide AI analyst with pgvector and Ollama-backed RAG.
  Commit `6fdd9d7`.

## [0.29.1] - 2026-06-22

- Merged season and cross-match analytics. Commit `13c5299`.

## [0.29.0] - 2026-06-22

- Added season and cross-match analytics, including Season page and Metabase SQL.
  Commit `14aa5cd`.

## [0.28.1] - 2026-06-22

- Merged match setup and metadata changes. Commit `a0028ed`.

## [0.28.0] - 2026-06-22

- Added match setup metadata for competition and structured date.
  Commit `91bf046`.

## [0.27.1] - 2026-06-14

- Merged test suite and CI. Commit `fe6fa15`.

## [0.27.0] - 2026-06-14

- Added pytest suite and GitHub Actions CI. Commit `a8ca7fd`.

## [0.26.1] - 2026-06-14

- Merged Docker analytics stack. Commit `5657d48`.

## [0.26.0] - 2026-06-14

- Added Docker analytics stack: Metabase, pg backups, pgvector semantic search.
  Commit `bd07a13`.

## [0.25.0] - 2026-06-14

- Wired the app to Docker Postgres and fixed pgAdmin reserved-domain crash.
  Commit `6126371`.

## [0.24.1] - 2026-06-14

- Merged match library: Postgres index, media store, UI, export-match zip, and
  backfill. Commit `d876480`.

## [0.24.0] - 2026-06-14

- Added Library Phase 5: backfill importer and delete-match. Commit `ae7c090`.

## [0.23.0] - 2026-06-14

- Added Library Phases 3 and 4: Match Library UI and export-match zip.
  Commit `1fc754f`.

## [0.22.0] - 2026-06-14

- Added Library Phase 2: finalize a match into the library. Commit `114aa41`.

## [0.21.0] - 2026-06-14

- Added Library Phase 1: media store and match registration. Commit `c7a6002`.

## [0.20.0] - 2026-06-14

- Added Library Phase 0: Postgres data layer and Docker infrastructure.
  Commit `7ad47c5`.

## [0.19.3] - 2026-06-14

- Expanded the library plan with Docker infrastructure scope. Commit `db06429`.

## [0.19.2] - 2026-06-14

- Added `LIBRARY_PLAN.md` for Postgres-backed match library and export-match
  design. Commit `ebdd873`.

## [0.19.1] - 2026-06-14

- Merged richer data/report exports and possession bug fixes. Commit `3d4a2a8`.

## [0.19.0] - 2026-06-14

- Improved data and report exports; fixed latent possession and Passes bugs.
  Commit `a213f30`.

## [0.18.6] - 2026-06-14

- Merged device auto-detect for MPS, CUDA, and CPU. Commit `5170025`.

## [0.18.5] - 2026-06-14

- Merged share card PNG export. Commit `34b8848`.

## [0.18.4] - 2026-06-14

- Merged undo-last-event button. Commit `98bb182`.

## [0.18.3] - 2026-06-14

- Merged thoughts mode, lineups, and audio quality changes. Commit `43d59dd`.

## [0.18.2] - 2026-06-14

- Updated `DEVELOPMENT_PLAN.md` and cleaned up lint warnings. Commit `692184d`.

## [0.18.1] - 2026-06-14

- Added `DEVELOPMENT_PLAN.md` with the 8-phase roadmap. Commit `3c6591b`.

## [0.18.0] - 2026-06-14

- Added automatic best inference device detection for MPS, CUDA, and CPU.
  Commit `4147d1c`.

## [0.17.0] - 2026-06-14

- Wired share card export into the dashboard export section. Commit `d79b5ff`.

## [0.16.0] - 2026-06-14

- Added undo-last-event button to the main scoreboard. Commit `b711e49`.

## [0.15.0] - 2026-06-14

- Reconciled stash and remote work with thoughts mode, lineups, and audio
  improvements. Commit `f4da4d8`.

## [0.14.1] - 2026-06-14

- Added `NEXT_STEPS.md` handoff for laptop pickup. Commit `4631a83`.

## [0.14.0] - 2026-06-14

- Included trained model, dataset, and setup docs in-repo for laptop and PC
  access. Commit `21db9fd`.

## [0.13.0] - 2026-06-14

- Added manual entry page and design wireframes; kept tracker/timeline/stats WIP
  notes. Commit `07597d5`.

## [0.12.2] - 2026-06-14

- Added `--workers` knob to training to avoid CPU-RAM OOM on constrained systems.
  Commit `4c67fb1`.

## [0.12.1] - 2026-06-14

- Added `ANNOTATION.md` dataset, GPU training, and laptop deployment guide.
  Commit `c1349b3`.

## [0.12.0] - 2026-06-14

- Added AI analyst over vision spatial findings. Commit `26573b4`.

## [0.11.0] - 2026-06-14

- Added local computer-vision pipeline ("the Eye") and live UI. Commit `7bfad86`.

## [0.10.0] - 2026-06-08

- Implemented wireframe design system with CSS tokens, scoreboard, comparison
  bars, feed, and page headers. Commit `9ab60db`.

## [0.9.0] - 2026-06-08

- Added Insights page with momentum graph and local AI match analyst.
  Commit `2d49da4`.

## [0.8.0] - 2026-06-08

- Completed sports-tech HUD theme UI redesign. Commit `abd17af`.

## [0.7.0] - 2026-06-07

- Rebranded the app to Kickoff Pulse with brand kit. Commit `7e09dd3`.

## [0.6.0] - 2026-06-07

- Added Windows support, event deletion, and match naming. Commit `2f2a7ce`.

## [0.5.0] - 2026-06-07

- Added glowing recording indicator; fixed timeline clutter and warning flood.
  Commit `1e9c8de`.

## [0.4.1] - 2026-06-06

- Removed emoji from launch banner and added watchdog for quieter Streamlit.
  Commit `571c4c8`.

## [0.4.0] - 2026-06-06

- Added visual Timeline page with icon badges, details, and image export.
  Commit `374b640`.

## [0.3.0] - 2026-06-06

- Added match clock, player stats, reports, pause, and post-match summary.
  Commit `e507969`.

## [0.2.0] - 2026-06-06

- Added more match metrics: saves, cards, corners, offsides, and pass accuracy.
  Commit `69a4b73`.

## [0.1.0] - 2026-06-06

- Initial KickoffAI local real-time soccer stats tracker. Commit `f091d6e`.
