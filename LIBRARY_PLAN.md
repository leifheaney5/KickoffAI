# Kickoff Pulse — Match Library & Database Plan

A local **Postgres-backed match library** with a sleek Streamlit UI to browse
every match and its artifacts (reports, data, audio, images, video), plus a
one-click **Export match** that zips everything for a match together.

---

## The core problem

Matches are **not first-class** in the app today:

- Report artifacts are timestamped (`match_report_20260610_205359.pdf`) with no
  shared match ID.
- `match_name` lives in `control.json` for the *current* match only.
- Media (audio in `notes_audio/`, `clip.mp4`, vision `match_stats.json`) sits at
  the repo root with nothing linking it to a match.

So the foundational work is introducing a **match entity** and a **managed media
store**, then indexing both in Postgres and surfacing them in a Library UI.

---

## Design decisions

1. **Postgres is the index, not the blob store.** Metadata (matches, events,
   file records) lives in Postgres; the actual files stay on disk. Storing large
   audio/video in a DB is an anti-pattern and makes zip export awkward.
2. **Managed media store, organized by match.** Each match owns a folder:
   `library/<match_slug>/{reports,data,audio,images,video}/`. Because every
   file for a match lives under one folder, **Export match = zip that folder** —
   trivial and reliable.
3. **SQLAlchemy data-access layer.** Backend-agnostic so we get Postgres as
   requested but can fall back to SQLite for zero-setup dev. One `db.py` module
   owns the engine, session, and models.
4. **Finalize step makes a match permanent.** A "Save to library" action
   snapshots the current live files (`match_data.json`, notes + audio, vision
   output, generated reports) into the match's folder and writes DB rows.
5. **UI attaches to the existing app** as a new `pages/6_Match_Library.py`,
   reusing `brand.py` styling so it stays on-theme.

---

## Schema (Postgres)

```text
matches
  id            uuid pk
  slug          text unique         -- e.g. 2026-06-10-hub-city-vs-frederick
  name          text
  played_on     date
  home_team     text
  away_team     text
  home_score    int
  away_score    int
  summary       text
  created_at    timestamptz
  updated_at    timestamptz

events                              -- optional: queryable event log per match
  id            bigserial pk
  match_id      uuid fk -> matches
  match_time    text
  team          text
  player        text
  action        text
  result        text
  location      text
  raw_text      text

media_files                        -- the navigable index of every artifact
  id            uuid pk
  match_id      uuid fk -> matches
  kind          text                -- report_pdf | report_txt | events_csv |
                                    --   team_csv | player_csv | data_json |
                                    --   timeline_png | audio_note | image | video
  path          text                -- relative to library root
  label         text
  bytes         bigint
  created_at    timestamptz
```

---

## Phased roadmap

### Phase 0 — Postgres + data-access layer

**Branch:** `feature/library-db` · **Size:** M · No blockers

- Add `psycopg[binary]` + `SQLAlchemy` to `requirements.txt`.
- `db.py`: engine from `KICKOFF_DB_URL`
  (`postgresql+psycopg://…`, default to local SQLite `library.db` if unset),
  SQLAlchemy models for the schema above, `init_db()` to create tables.
- Document local Postgres setup (Docker one-liner + `brew` path) in the plan's
  setup section / a short `LIBRARY_SETUP.md`.

**Done when:** `python -c "import db; db.init_db()"` creates the schema against a
local Postgres instance.

### Phase 1 — Match entity + media store

**Branch:** `feature/library-store` · **Size:** M · Depends on Phase 0

- `library.py`: helpers to create a match (slug from name + date), resolve its
  folder, and register a file (copy into the right subfolder + insert a
  `media_files` row).
- `LIBRARY_ROOT` env (default `library/`), gitignored.

**Done when:** A unit call creates a match, copies a file in, and the row is
queryable.

### Phase 2 — Finalize / save-to-library

**Branch:** `feature/library-finalize` · **Size:** M · Depends on Phase 1

- "Save match to library" action: snapshot the current live state — generate the
  report bundle (reuse `report.generate`), then register the reports, the data
  JSON/CSVs, every note's audio clip, any vision output, and a linked video — and
  write the `matches` + `events` rows.
- Hook: offer this from the dashboard's export panel ("Save & archive match").

**Done when:** Finalizing the current match produces a populated
`library/<slug>/` folder and DB rows for every artifact.

### Phase 3 — Library UI (browse & preview)

**Branch:** `feature/library-ui` · **Size:** L · Depends on Phase 2

- `pages/6_Match_Library.py`, brand-styled:
  - **List view:** searchable/sortable cards (name, date, score, artifact
    counts). Filter by date / team.
  - **Detail view:** artifacts grouped by kind with inline previews —
    `st.audio` for notes, `st.image` for stills, `st.video` for clips, download
    buttons for PDF/TXT/CSV/JSON.
- Empty states and a "no library yet" hint.

**Done when:** You can open the Library page, find a match, play its audio, view
its timeline image, and download its PDF.

### Phase 4 — Export match (zip)

**Branch:** `feature/library-export` · **Size:** S · Depends on Phase 3

- "Export match" button on the detail view zips `library/<slug>/` in-memory and
  serves it via `st.download_button` as `<slug>.zip`.
- Manifest (`match.json`) written into the zip with metadata + file list.

**Done when:** Clicking Export downloads a single zip containing every file for
the match plus a manifest.

### Phase 5 — Backfill + polish

**Branch:** `feature/library-backfill` · **Size:** M · Depends on Phase 4

- One-off importer: scan existing `reports/` (group by the shared timestamp) and
  any root media, create matches, and register the files.
- Delete-match (DB row + folder), dedupe, and basic integrity checks
  (orphan rows / missing files).

**Done when:** Existing reports appear in the Library without manual entry.

---

## Dependency map

```text
Phase 0 (db layer)
  └── Phase 1 (match entity + store)
        └── Phase 2 (finalize)
              └── Phase 3 (UI)
                    └── Phase 4 (export zip)
                          └── Phase 5 (backfill + polish)
```

Strictly sequential — each phase builds on the previous. Phases 0–2 are
backend-only (testable headless); the UI lands in Phase 3.

## Locked decisions

- **Postgres hosting:** local **Docker container** — most reproducible, easy to
  reset. `db.py` still falls back to SQLite when `KICKOFF_DB_URL` is unset so
  the app runs without Docker during dev.
- **Video handling:** **copy clips into the match folder** so every match is
  self-contained and the export zip is always complete.
- **Events:** **mirror the full event log into Postgres** (the `events` table)
  to enable cross-match queries and season-level stats later.
