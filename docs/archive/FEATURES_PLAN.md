# Feature plan — clips, player development, share packs

Three features that compose into one loop: the **moment**, the **trend**, and a
way to **hand both to the player**.

Deliberately built on the event log and the video file, not on vision-derived
numbers. Ball detection is still the ceiling (`quality.py` grades most runs
*indicative*), so anything spatial would ship caveated. Events and video are
reliable today.

---

## The alignment problem, and why it dissolves

Clipping needs to know where in the video a match event happened. The obvious
approach — map match-clock time to video time — breaks on the half-time gap: the
match clock stops at 45:00 while the video keeps rolling, so every second-half
event lands minutes early. This is the same misalignment the `analyze-video`
skill already warns about.

**Wall clock removes the problem.** Every event carries an ISO `timestamp`, and a
recording knows when it started:

```
video_position = event_timestamp - recording_started_at
```

No offsets, no half-time correction, no assumptions about when kickoff was.
Recording is one continuous file, so this holds for the whole match.

Two cases:

- **Recorded by the app** (`screen_recorder`): `started_at` is already stored, so
  alignment is automatic and needs no input at all.
- **Recorded elsewhere** (Veo, a phone): the user sets the recording start once
  per match. To avoid asking for a wall-clock time nobody knows, they instead
  scrub to a known event — "the first goal is at 12:30 in the video" — and the
  anchor is derived from that event's timestamp.

---

## Feature 1 — Automatic clips

**Why.** Nobody watches a 90-minute match video; everybody watches the goal. The
app already stores the video and timestamps every event, and `key_moments()`
already picks out what matters. Nothing cuts between them.

**Build.**

- `clips.py`, pure and testable apart from the ffmpeg call:
  - `video_position(event, anchor)` — wall clock to video seconds
  - `plan_clips(events, anchor, pre=8, post=12)` — what to cut and what to call
    it, returned before anything runs so the UI can show it
  - `extract(plan, video, out_dir)` — `ffmpeg -ss … -t … -c copy` per clip, with
    a re-encode fallback when a stream copy will not cut cleanly on a keyframe
- Clip what a coach actually reviews: goals, cards, shots on target, and
  cross-source *confirmed* key moments. Not every pass.
- Register clips as library media (`kind="video"`), so they archive and sync with
  the match like any other artifact.
- A **Clips** section on Post-Match: set the anchor, preview the plan, extract,
  then play them inline.

**Done when:** archiving a match with a video yields a folder of watchable
moments without anyone typing a timestamp.

**Risks.** `-c copy` cuts on keyframes, so a clip can start up to a GOP early;
acceptable for review, and the re-encode path is there when it is not. Long
videos make extraction slow — run it as an explicit action, never on archive.

## Feature 2 — Player development

**Why.** `season.py` computes standings and top scorers and nothing else, yet the
mirrored `events` table has carried a `player` on every row all along. A youth
coach's actual job is developing players, and the app currently cannot say how
any player is progressing.

**Build.**

- `player_season(rows)` in `season.py`: appearances, per-match contribution, and
  a per-metric trend across the season for each player.
- A **Players** view on the Season page: pick a player, see their match-by-match
  line, their season totals, and how their recent form compares to their own
  baseline — not to the squad, which for a youth team says little.
- Works on audio-logged tokens (`#6`) today; improves untouched when jersey
  identity lands, because the data shape does not change.
- Squad view: appearances per player, so uneven involvement is visible. Many
  youth leagues expect roughly equal playing time, and nothing currently shows it.

**Done when:** a coach can answer "how is #9 doing this season?" from the app.

## Feature 3 — Player share pack

**Why.** Clips without a way to send them stay in a folder; a development trend
nobody sees is a chart for one person. This is the distribution step, and it is
mostly assembly — `player_stats()`, the share-card renderer and (from feature 1)
clips already exist.

**Build.**

- A per-player bundle: their match line, their clips, and their season trend.
- Two outputs: a portrait card for messaging (extending `share_image.py`), and a
  zip for a parent who wants the clips themselves.
- Generated on Post-Match beside the existing team share card.
- Contains only that player: no squad-wide stats, no other children's names.

**Done when:** a coach can send one player exactly what is about them, in a form
a parent will open.

---

## Sequencing

1 → 3 (the pack wants clips), and 2 is independent. Feature 1 first: it is the
foundation and the largest.

| Feature | Size | Depends on |
|---|---|---|
| 1 Clips | L | ffmpeg (already required) |
| 2 Player development | M | — |
| 3 Share pack | M | 1 |

## Deliberately out of scope

Anything spatial — shape over time, pressing patterns, positional heatmaps per
player — until the retrain lifts ball detection. Those would ship graded
*indicative* and would teach coaches to distrust the numbers.

## Open question

**Clip length.** 8s before and 12s after an event is a starting guess. Real
review usually wants more build-up for a goal than for a card, so this may want
to vary by event type once there are clips to watch.
