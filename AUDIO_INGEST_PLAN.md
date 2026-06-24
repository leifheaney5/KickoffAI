# Audio Ingest — Improvement Plan

Hardening pass for the live audio pipeline after the v1.5.0 feedback-loop
release. The pipeline today is correct but **single-threaded and I/O-heavy**: the
microphone capture, Whisper transcription, and Ollama parse all run in sequence
on one loop, and several sidecar files are re-read and fully rewritten on every
utterance. These phases remove dropped audio, cut hot-loop latency, and stop the
review/audio stores from growing without bound.

Each phase ships on its own branch and can be reviewed/merged independently.
Phases are ordered by value; Phase 1 and 2 pair naturally and should land first.
Per the repo rule, every merge updates `CHANGELOG.md` and rolls the app version.

Affected files: `audio_tracker.py`, `audio_ingest.py`, `audio_benchmark.py`,
`pages/Audio_and_Mic.py`, plus tests under `tests/`.

---

## Phase 1 — Threaded capture (no more dropped audio)

**Branch:** `feature/audio-threaded-capture` · **Size:** M · No blockers

The headline issue. The main loop ([audio_tracker.py:891-1058](audio_tracker.py#L891-L1058))
runs `listen()` → `transcribe()` → `parse_event()` synchronously, so while
Whisper (1–3 s on `medium.en`) and Ollama (POST timeout **60 s** at
[audio_tracker.py:560](audio_tracker.py#L560)) are working, the mic is **not
being read**. Fast play-by-play spoken during that window is lost.

Split capture from processing with a bounded queue.

**Tasks:**

1. Add a capture thread that only runs `recognizer.listen()` and pushes
   `(audio, captured_at)` onto a `queue.Queue(maxsize=N)` (default ~8).
2. Move transcription + gate + parse + persistence into a consumer worker that
   drains the queue. Keep it single-consumer first (Whisper isn't reentrant on
   one model instance) — capture is what we must never block.
3. On `queue.Full`, drop the oldest item and increment a `dropped` counter in
   `status.json` so the dashboard can surface backpressure.
4. Keep the existing pause / calibration / thoughts-mode branches in the
   consumer; the capture thread keeps filling the queue (or is gated) while
   paused — pick one and document it.
5. Reuse the SIGINT/SIGTERM `running` flag to stop both threads cleanly; join
   with a timeout so Ctrl+C stays responsive.

**Done when:** speaking two phrases back-to-back (second one starting while the
first is still transcribing) logs **both** events; `status.json` exposes a
`queued` / `dropped` count.

---

## Phase 2 — In-memory transcription (cut per-phrase I/O)

**Branch:** `feature/audio-inmemory-transcribe` · **Size:** S · Pairs with Phase 1

Every utterance is written to a temp `.wav`, transcribed from that path, then
unlinked ([audio_tracker.py:913-922](audio_tracker.py#L913-L922)). Both Whisper
backends accept an in-memory `float32` numpy array, so the disk write + read +
unlink per phrase is avoidable.

**Tasks:**

1. Add a helper that converts `AudioData` (16-bit PCM) to a mono `float32`
   numpy array normalised to [-1, 1], resampled to 16 kHz if needed.
2. Pass the array straight to `mlx_whisper.transcribe(...)` /
   `whisper.transcribe(...)` instead of a path.
3. Keep `write_wav` only for the paths that genuinely persist audio (review
   clips, thoughts notes) — those still need a file.
4. Verify mlx-whisper segments still carry `no_speech_prob` / `avg_logprob`
   (see Phase 5) when fed an array.

**Done when:** the benchmark and live loop produce identical transcripts to the
WAV path with no temp `.wav` created per phrase, and avg latency drops.

---

## Phase 3 — Cache corrections + cheaper sidecar writes

**Branch:** `feature/audio-hotloop-io` · **Size:** S · No blockers

Two hot-loop I/O problems:

- `apply_corrections` → `apply_learned_corrections` re-reads and re-parses
  `corrections.json` for **every** transcript ([audio_ingest.py:188-191](audio_ingest.py#L188-L191)).
- `append_event` and `append_review` **load the whole list and rewrite the
  entire file** on every call ([audio_tracker.py:647-660](audio_tracker.py#L647-L660),
  [audio_ingest.py:79-83](audio_ingest.py#L79-L83)). `write_review` also fires on
  every ignored blip ([audio_tracker.py:990](audio_tracker.py#L990)), so the
  review store is O(n²) over a match.

**Tasks:**

1. Cache parsed corrections with an mtime check; reload only when
   `corrections.json` changes. Keep the usage-counter write but batch it (flush
   on an interval / on shutdown) instead of per-hit.
2. Move the review log to append-only JSONL **or** a `db.py` SQLite table so a
   new review is an append, not a full rewrite. Provide a reader that the
   dashboard uses; keep a one-time migration from the existing
   `audio_reviews.json`.
3. Leave `match_data.json` as a JSON array (the rest of the app reads it whole),
   but confirm the rewrite cost is acceptable, or add the same JSONL-backed
   store with a materialised array on finalize.

**Done when:** correction lookups do no disk read in steady state; appending the
1000th review costs the same as the 10th (no full-file rewrite).

---

## Phase 4 — Duplicate / cooldown suppression

**Branch:** `feature/audio-dedupe` · **Size:** S · No blockers

No debounce exists. Repeated calls ("goal, goal!") or near-identical adjacent
windows produce duplicate events.

**Tasks:**

1. Track the last accepted event's `(action, team, player)` + timestamp.
2. Suppress an identical signature within a configurable cooldown
   (`KICKOFF_DEDUPE_SEC`, default ~6 s); log the suppression to `status.json`
   (`last_ignored_reason = "duplicate"`) and a review record so it stays
   reviewable.
3. Make the window per-action (a goal cooldown ≠ a pass cooldown) if testing
   shows one global value is too blunt.

**Done when:** saying the same call twice within the window logs one event;
saying it after the window logs two.

---

## Phase 5 — Robustness: mic recovery + confidence gate verification

**Branch:** `feature/audio-robustness` · **Size:** S · No blockers

Two reliability gaps:

- On an `OSError` mid-match the loop sleeps 0.5 s and retries the **same stale
  `device_index`** ([audio_tracker.py:898-901](audio_tracker.py#L898-L901)). If
  AirPods drop and reconnect at a new index, capture never recovers.
- The Whisper confidence gate ([audio_tracker.py:229-237](audio_tracker.py#L229-L237))
  reads `no_speech_prob` / `avg_logprob` from segments — but mlx-whisper (the
  default Apple-Silicon backend) may not populate them, silently disabling the
  gate.

**Tasks:**

1. On repeated mic read failures (N in a row), re-run `pick_microphone()` to
   re-resolve `KICKOFF_MIC` and re-open the device; surface a `mic_error` state.
2. Add a unit/inspection check that asserts which confidence keys the active
   backend returns; if mlx omits them, document it and fall back to the
   compression-ratio / repetition heuristics already in `is_real_speech`.
3. Make the hallucination filter prefix/substring-aware so
   "thanks for watching so much" is caught, not just exact matches
   ([audio_tracker.py:214-216](audio_tracker.py#L214-L216)).

**Done when:** unplugging and reconnecting the mic mid-session resumes capture
without a restart; a test documents the real per-backend segment fields.

---

## Phase 6 — Retention for review / notes audio

**Branch:** `feature/audio-retention` · **Size:** S · No blockers

Every clip is saved as uncompressed WAV in `review_audio/` and `notes_audio/`
([audio_ingest.py:150-158](audio_ingest.py#L150-L158)) with no cap. A full match
is thousands of WAVs.

**Tasks:**

1. Add a retention policy: cap by count and/or age, pruning oldest review clips
   (keep notes — those are user-authored) past the cap.
2. Optionally encode clips to FLAC (lossless, ~50% smaller) on save; update the
   dashboard player to read them.
3. Run pruning on tracker shutdown and/or at match finalize; never delete clips
   still referenced by a pending (un-reconciled) review.

**Done when:** a long session keeps `review_audio/` under a configurable size
budget without losing clips for un-reviewed events.

---

## Phase 7 — Benchmark upgrades (regression guard)

**Branch:** `feature/audio-benchmark-plus` · **Size:** S · No blockers

`audio_benchmark.py` lumps transcription + parse latency
([audio_benchmark.py:145-149](audio_benchmark.py#L145-L149)) and scores text at
the character level only.

**Tasks:**

1. Report `transcribe_ms` and `parse_ms` separately so a regression can be
   localised to the Ear or the Brain.
2. Add a word-level WER alongside the existing `SequenceMatcher` ratio.
3. Add a dedupe-aware mode so Phase 4's cooldown can be regression-tested.

**Done when:** `python audio_benchmark.py --manifest ...` prints split latencies
and a WER, and CI/tests assert the starter cases stay above a threshold.

---

## Dependency map

```text
Phase 1 (threaded capture)  ← headline
  └── Phase 2 (in-memory transcribe)   ← pairs with 1

Phase 3 (hot-loop I/O)      ← independent
Phase 4 (dedupe)            ← independent (easier to test after Phase 7)
Phase 5 (robustness)        ← independent
Phase 6 (retention)         ← independent
Phase 7 (benchmark)         ← independent; do early to guard 1–4
```

## Suggested order

1. **Phase 7** first (cheap) so later phases have a latency/accuracy guard.
2. **Phase 1 + 2** together — the real-world win (no dropped audio, lower latency).
3. **Phase 3** — safe hot-loop cleanup.
4. **Phase 4, 5, 6** — independent hardening, any order.

## Acceptance criteria (overall)

- No audio dropped when phrases overlap processing (Phase 1).
- Per-phrase latency measurably lower; no temp WAV per utterance (Phase 2).
- Steady-state correction lookups do zero disk reads; review appends are O(1)
  (Phase 3).
- Repeated calls within the cooldown log once (Phase 4).
- Mic reconnect resumes without a restart (Phase 5).
- Review-audio disk stays within budget (Phase 6).
- Benchmark reports split latency + WER and gates regressions (Phase 7).

## Risks

| Risk | Mitigation |
|---|---|
| Threaded refactor introduces races on `status.json` | single consumer owns status writes; capture thread only enqueues |
| Queue backpressure hides dropped speech | surface `dropped` count in dashboard; size queue generously |
| In-memory array diverges from WAV path accuracy | Phase 7 benchmark asserts identical transcripts before switch |
| JSONL/SQLite review store breaks existing dashboard reader | one-time migration + compatibility reader; keep old file until verified |
| Dedupe drops a genuine second event | per-action cooldown, keep suppressed items as reviews, make window configurable |
| FLAC encode adds latency on save | encode off the capture thread; WAV remains the fallback |
</content>
</invoke>
