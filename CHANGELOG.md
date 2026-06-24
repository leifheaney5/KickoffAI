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
