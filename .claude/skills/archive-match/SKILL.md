---
name: archive-match
description: Finalize the current match into the Kickoff Pulse match library so it is browsable and exportable later, optionally bundling a video file. Use when asked to archive, finalize, or save a match to the library.
---

# Archive a match to the library

`finalize.finalize_match()` snapshots the current match (events, stats, state,
notes) into the match library and returns its slug. All inputs default to the
live working files, so it can be called with no arguments at the end of a match.

## Run it

From the repo root:

```bash
.venv/bin/python -c "import finalize; print('archived:', finalize.finalize_match())"
```

To bundle a match video at the same time:

```bash
.venv/bin/python -c "import finalize; print('archived:', finalize.finalize_match(video_path='recordings/match.mp4'))"
```

Report the returned slug and tell the user it is now in the **Match Library**
page (browse / export there).

## Requirements

- A reachable database: live use expects **Postgres** (`docker compose up -d`,
  localhost:5432). For dev SQLite set `KICKOFF_ALLOW_SQLITE=1` /
  `KICKOFF_DB_URL=sqlite:///...`.
- The match data should be complete first — stop the audio tracker and any
  recording before archiving so the snapshot is final (see `app-doctor`).

## Related

- Generate the shareable report bundle with `generate-report` (separate from the
  library archive).
