# Club plan — from one coach to a club

**From:** v1.13.0 (single-user, single-match, local files)
**To:** several coaches capturing their own matches, sharing one library.

## Assumptions

1. **Self-hosted.** The club runs its own Postgres (the existing
   `docker-compose.yml` stack). No cloud, no API keys — the project's ethos.
2. **Offline-first capture.** A pitch often has no signal, so capture must work
   fully disconnected and sync afterwards. This is the harder path and it is the
   correct one.
3. **Each coach captures on their own machine.** Concurrent matches then come
   free. Several simultaneous captures on *one* box is explicitly out of scope —
   the runner's PID files and fixed output paths make that a different problem.

## The core structural problem

The archive is already a database. The **live match is not** — it is a set of
singleton files in the repo root (`match_data.json`, `control.json`,
`status.json`, `notes.json`, `match_stats.json`), owned by nobody and belonging
to no particular match. That is why matches silently merge: there is no concept
of *which* match the files describe, so nothing can decide when to clear them.

There is also no user, owner, team, or role anywhere in the codebase, and the
shipped Postgres credentials are `kickoff/kickoff` on a published port — fine on
localhost, unacceptable the moment a club shares it.

## Architecture

Capture is inherently local (microphone, camera, GPU). The library and season are
inherently shared. So the split is:

```
Coach's laptop (mostly unchanged)        Club server (self-hosted)
  mic + camera -> the Eye / the Ear        Postgres + auth
  local match files (one live match)       shared library, season
  Streamlit console                        read-only club view
        |                                        ^
        +---- sync finished matches -------------+
                (explicit, offline-tolerant)
```

Everything expensive stays local; the vision pipeline, report generator and trust
gate are reused unchanged.

---

## S0 — Match identity + reset

The correctness fix, and the prerequisite for everything after it.

- `match_id` (UUID) in `control.json` identifies the current match.
- Every event, note and vision run is stamped with it.
- `control.new_match()` archives-or-refuses, then clears the working files and
  mints a new id.
- A **New match** action in the UI, with a guard against discarding unarchived
  work.

**Done when:** starting a second match cannot merge it into the first.

## S1 — Single-user hardening

Needed whoever uses it.

- Recordings retention (6.2 GB and unbounded today; a full disk kills a match).
- A dependency lockfile — everything is `>=` with no reproducible environment.
- Tests for `control.py`, the clock and shared-state module, currently untested.
- Live soak on a real Veo stream *(blocked: needs a stream URL)*.

## S2 — Users, teams, ownership

- `users`, `teams`, `team_members`; `matches.owner_id` / `matches.team_id`.
- Password hashing (PBKDF2-HMAC-SHA256, per-user salt) and session tokens.
- A login gate on the app; matches scoped to the viewer's teams.
- Real Postgres credentials, not `kickoff/kickoff`.

**Security scope:** this is LAN-appropriate authentication for a self-hosted club
server. It is not hardened for exposure to the open internet — that would need
TLS termination, rate limiting, and a security review beyond this plan.

## S3 — Offline-tolerant sync

- Finished matches queue locally and push when the server is reachable.
- Idempotent by match UUID, so a retry can never duplicate a match.
- Clear per-match sync state: `local` / `pending` / `synced` / `conflict`.

## S4 — Club views

- Season and library scoped by team.
- Coverage and possession trends per team.

---

## Sequencing

S0 -> S1 -> S2 -> S3 -> S4. S0 and S1 deliver standalone value immediately; S2 is
the bulk of the work; S3 depends on S2's identity model.
