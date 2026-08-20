# UX, GUI and architecture plan

**From:** v1.14.0 — the capability is there; the *usability* has not kept pace.
**Through:** an app another coach can pick up unaided, use from the touchline,
and that keeps its interface coherent as it grows.

Four workstreams, independent enough to reorder: **A. UX**, **B. GUI debt**,
**C. Sideline view**, **D. Architecture**.

## Principles

1. **Evidence before optimisation.** The Match Console's four 1-second fragments
   were measured at ~2 ms per tick — about 11 seconds of CPU across a 90-minute
   match. Polling is *not* a problem and must not be "fixed".
2. **The app should teach itself.** With a club onboarding coaches who will not
   read a README, anything only you know is a defect.
3. **Never overclaim in the interface**, the same rule the trust gate follows.
4. **Fix conventions before they multiply.** Half the pages already diverged;
   every new page doubles down on whichever pattern it copies.

---

# Workstream A — UX

## A1. A first-run path

**Problem.** `pages/Match_Console.py` has *zero* empty-state handling;
`pages/Match_Setup.py` has zero; `pages/Camera_and_Feed.py` has one. A new coach
lands on a 0–0 scoreboard reading "Home" vs "Away" with no feed and no teams, and
nothing says what to do. The sequence — Camera & Feed → Test connection →
Match Console → Start — exists only in your head and the README.

**Build.**

- `setup_state()` in `ui_helpers.py`, a pure function returning what is ready and
  what is not: feed configured, feed tested, pitch calibrated, teams named,
  lineups entered, ingest mode chosen, vision deps present, weights on disk.
  Pure and testable — no Streamlit inside it.
- A **Get started** panel on the Match Console, shown only while the essentials
  are missing, listing the two or three remaining steps with links straight to
  the page that fixes each. It disappears once you are ready, so it never nags a
  returning user.
- Real empty states on every page that can be empty: Timeline, Insights, Season,
  Match Library, Team Shape, Film Room. Each says what is missing, why the page
  is blank, and the one action that fills it.
- A **readiness chip** on Camera & Feed summarising the same state, so setup can
  be confirmed before kickoff rather than discovered at kickoff.

**Done when:** a coach who has never seen the app can go from launch to a running
match without being told anything.

## A2. Make the match lifecycle visible

**Problem.** `match_id`, `archived_at` and `sync_state` all exist and surface on
exactly one page (Post-Match). From the console you cannot tell whether this
match is live, finished, archived, or pushed to the club. With deferred sync,
"did my match upload?" has no answer without navigating to Account — and the
answer matters most to the person who just drove home from a fixture.

**Build.**

- A **match chip** in the status bar beside the Eye and mic chips:
  `Live` → `Finished` → `Archived` → `Synced`, derived from the clock,
  `archived_at`, and the match's `sync_state`.
- The chip is the affordance: clicking it goes to the next action in the
  lifecycle (archive it, push it).
- A **sync badge** in the sidebar when matches are waiting to upload, so it is
  visible from anywhere rather than only on Account.
- Show the match name and id on the console, so two coaches on one machine can
  tell whose match is loaded.

**Done when:** the current match's state is legible from any page in one glance.

## A3. Consistent destructive actions

**Problem.** `New match` is guarded (it asks before discarding unarchived work).
Nothing else is. `Reset` silently wipes the match clock mid-game; `Undo last
event`, `Delete note`, `Clear saved calibration` and `Delete old recordings` all
act immediately. The guarding is accidental rather than designed.

**Build.**

- One `confirm_action()` helper with a single pattern: what will be lost, whether
  it can be recovered, and an explicit confirm for anything unrecoverable.
- Apply by consequence, not by uniformity — `Undo last event` is trivially
  redone and should stay one click; `Reset` during a live match is not.
- Undo where it is cheap: deleting a note could offer a brief undo rather than a
  confirm, which is less friction and safer.

**Done when:** no single click can destroy something unrecoverable without
saying so.

---

# Workstream B — GUI debt

## B1. Unify the two page conventions

**Problem.** The pages have split roughly in half.

| | Legacy — 7 pages | Modern — 8 pages |
|---|---|---|
| `set_page_config` | yes, illegal under `st.navigation` | no |
| `sys.path.insert` | yes | no |
| CSS entry | `brand.global_css()` | `brand.app_css()` |

Legacy: Timeline, Insights, Manual Entry, Team Shape, Season, Match Library,
Analyst. Streamlit currently tolerates the duplicate `set_page_config`, but that
is luck; `global_css()` is a bare alias for `app_css()`, so there are two names
for one thing. Every new page copies whichever neighbour it was written beside.

**Build.**

- One `ui_helpers.page_setup(kicker, title)` doing CSS, header and (later) the
  auth check in a single call. Every page starts with it and nothing else.
- Delete `set_page_config` from the seven legacy pages; the router owns it.
- Decide the `sys.path.insert` question deliberately: it exists so a page can be
  run standalone with `streamlit run pages/X.py`. Either keep that ability and
  document it, or drop it and standardise on the router. Half-and-half is the
  only wrong answer.
- Retire `global_css()` after updating callers.

**Done when:** every page opens identically, and a new page has one obvious
pattern to copy.

## B2. Remove the CSS conflicts

**Problem.** `pages/Manual_Entry.py` and `pages/Timeline.py` inject global CSS
through `components.html`, and they contradict each other — one sets `gap:4px` on
every horizontal block, the other `gap:0`. Whichever page you visited last wins
until a rerun. This is why those two pages could not simply be merged into tabs.

**Build.** Move both into `brand.py` as *scoped* classes applied to the specific
containers that need them, and delete the `components.html` injections.

## B3. Consolidate the design system

**Problem.** `ui_helpers.py` has ~25 render functions emitting hand-written HTML
strings, and `brand.py` carries 88 hard-coded pixel values. There is a real
component vocabulary here — chips, cards, section headers, feed rows, comparison
rows — but it is implicit, so each new surface reinvents it slightly differently.

**Build.**

- Write down the vocabulary: chip, card, section, feed row, metric, badge. One
  function per component, one CSS class per component.
- Replace the pixel literals with the spacing and size tokens `brand.py` already
  defines for colour. This is also the prerequisite for C.
- A single `kp-` class namespace, so app styles can never collide with
  Streamlit's own.

## B4. A rule for the sidebar

**Problem.** 16 entries across 5 groups, up from 13 when this work started. It
grows every release and nothing governs it.

**Build.** A stated rule — roughly four per group, and a group earns its place
only if it maps to a distinct moment in the match day. Move **Account** out of
the nav into a user menu; it is identity, not a workflow step.

---

# Workstream C — The sideline view

**Problem.** `brand.py` has three `@media` rules in ~500 lines: the app is
desktop-only, delivered in a pywebview window. But a coach during a match is on
the touchline, not at a laptop.

**This is cheaper than it looks.** Streamlit already serves over HTTP;
`desktop.py` simply binds it to `127.0.0.1`. A phone on the same wifi needs a
bind flag and a compact page — not a rewrite.

**Build.**

- `KICKOFF_LAN=1` binds Streamlit to `0.0.0.0` and prints the URL plus a QR code
  in the terminal. Off by default, and the launcher states plainly that this
  exposes the app to the local network.
- A single **Sideline** page, read-only and deliberately thin: scoreboard and
  clock, the latest Eye frame, the last handful of events, momentum. Nothing that
  writes, so a phone can never disturb a live capture.
- Responsive CSS. B3's tokens are the prerequisite — the pixel literals are what
  currently breaks narrow layouts.
- If club auth is on, the sideline view respects it. A LAN-bound app with a
  bypass would undo the whole of S2.

**Explicitly not in scope:** a native mobile app, or editing from the phone.
Read-only is most of the value at a fraction of the cost and risk.

**Done when:** a coach can watch the match state from their phone on the
touchline while the laptop captures.

---

# Workstream D — Architecture

## D1. Media does not sync (the sleeper)

**Problem.** `sync.py` pushes matches and events. It does **not** push the files:
`match_stats.json`, report PDFs, timeline images, voice notes and video all stay
on the capture laptop under `LIBRARY_ROOT/<slug>/<kind>/`, while `MediaFile` rows
reference paths relative to a root the server does not have. So the club library
has every number and none of the artifacts, and nobody notices until the first
coach asks why they cannot open another coach's report.

**Build.**

- Extend the push: after a match syncs, copy its media into a shared media root
  and mark each `MediaFile` synced.
- Make paths resolve per-install rather than assuming one root, so a laptop and
  the server can hold the same match at different locations.
- Push media **after** the match row, and let it resume: a 2 GB video over club
  wifi will be interrupted, and that must not roll back the match itself.
- Size limits and an opt-out. Syncing every video by default would saturate the
  connection; reports and stats are small and always worth pushing.

**Done when:** a coach can open another coach's report from the club library.

## D2. The live layer is still singleton files

**Problem.** `match_id` gave matches identity, but the working files remain
singletons in the repo root. One match per machine: you cannot review last week's
while capturing this week's, and two coaches cannot share a laptop.

**Assessment.** The right end state is the live layer in the database, matching
where the archive already is. It is also a genuine project — every read path in
the app currently assumes those files. **Defer it** until the club install
produces a concrete case that demands it; the capture/shared split is holding up
well and this would be change for its own sake today.

**Cheap interim:** per-match working directories keyed by `match_id`, so
switching matches is swapping a pointer rather than clearing files. Most of the
benefit, a fraction of the work.

## D3. Test what usability, not just rendering

**Problem.** Page tests assert "renders without an exception", which says nothing
about whether the page is *usable*. The UUID coercion bug passed every unit test
and only fell out of an end-to-end flow.

**Build.** A handful of flow tests over the paths that matter — first run to live
match, match to archive to new match, capture to sync to another user's view —
driven through `AppTest` interactions rather than page loads.

---

# Sequencing and size

| Workstream | Size | Depends on | Ship value |
|---|---|---|---|
| A1 first-run | M | — | High — the club onboarding blocker |
| A2 lifecycle chips | S | — | High — answers "did it upload?" |
| A3 destructive actions | S | — | Medium |
| B1 page conventions | M | — | Medium — stops the split widening |
| B2 CSS conflicts | S | B1 | Medium |
| B3 design system | M | B1 | Enables C |
| B4 sidebar rule | S | — | Low but cheap |
| C sideline view | L | B3 | High — changes how it is used |
| D1 media sync | M | — | High once the club is real |
| D2 live layer in DB | XL | — | Deferred deliberately |
| D3 flow tests | M | A | Medium — catches the class of bug that got through |

**Recommended order.** A1 + A2 + B1 + B2 as one release: they touch the same
files, and together turn the app from "works if you know it" into "works if you
don't". Then D1, because it is invisible until it is embarrassing. Then B3 → C,
which is the largest change in how the product is used. D2 stays parked.

## Risks

| Risk | Mitigation |
|---|---|
| Convention unification breaks a page subtly | Flow tests (D3) before B1, not after |
| LAN binding exposes the app | Off by default; auth respected; launcher says so |
| Media sync saturates club wifi | Reports/stats by default, video opt-in, resumable |
| First-run guidance nags returning users | Driven by `setup_state()`, disappears when ready |

## Open questions

1. **Standalone pages** — keep `streamlit run pages/X.py` working, or standardise
   on the router? It decides whether `sys.path.insert` stays.
2. **Sideline auth** — with club mode off, is a LAN-bound sideline view open to
   anyone on the wifi, or does it get a simple shared code?
3. **Video sync** — push by default, or always opt-in? Depends on whether the
   club's wifi is worth trusting with gigabytes.
