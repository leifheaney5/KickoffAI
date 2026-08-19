# Master plan — Kickoff Pulse as a football intelligence engine

Merges `EYE_PLAN.md` (ingest + live analytics + the stat programme) with the
Opta-style analytics platform specification. Supersedes both.

**The specification is adopted in full on architecture and discipline, and
scaled deliberately on ambition.** Where it is changed, the change and its reason
are stated — silently dropping half a spec is worse than arguing with it.

---

## 1. The unifying principle

The specification's closing principle and this product's trust gate are the same
idea, and it becomes the spine of everything below:

> **Events are facts. Metrics are reproducible interpretations of those facts.
> Models are versioned estimates built on top of them.**

Kickoff Pulse already ships the fourth clause the specification implies but never
names: **every number says how much to trust it.** `quality.py` grades camera
runs *measured / indicative / unusable*. The master plan extends that from runs
to every metric in the catalogue.

That is also the answer to "our own way": Opta hands you a table where a
hand-tagged shot and a modelled xG carry identical visual weight. Ours will not.

---

## 2. Current state audit

Required by §91 before any code changes.

| Area | Today | Spec expects |
|---|---|---|
| **DB entities** | `users`, `teams`, `team_members`, `matches`, `events`, `media_files` | + Competition, Season, Player, MatchPlayer, Period, Qualifier, Possession, Sequence |
| **Event model** | Flat dict, 11 keys, no coordinates — `location` is free text (`"box"`) | Normalised x/y, end_x/end_y, qualifiers, possession/sequence links |
| **Coordinates** | Vision emits **0–100 normalised** already | 0–100 normalised — **already aligned** |
| **Taxonomy** | 13 action types, 16 stat keys, hard-coded in two files | ~100 event types, registry-driven |
| **Possessions / sequences** | None | Reconstruction engines |
| **Models** | None | xG, xGOT, xA, xT, PV |
| **Tracking** | The Eye *is* a tracking source — ~4/22 players, 4–12% ball | Multi-camera, 25 Hz |
| **Provenance** | Per-run (`quality.py`), not per-metric | Per-datum |
| **Scale** | 223 events, 6 matches, 1 team | Multi-competition |

**Reusable as-is:** normalised coordinates, `vision/analytics.py` (zones, thirds,
territory, shape), `vision/render.py` (pitch drawing), `quality.py` (the
provenance mechanism), `clips.py` (evidence behind a stat), the Postgres library,
`sync.py`, the offline-first capture path.

**The blocking gap:** logged events carry no coordinates. Most spatial analytics
cannot run on the audio half until they do.

---

## 3. Where the specification is adapted, and why

Adopting a server-platform architecture unchanged would trade away this product's
defensible position and build for data we do not have. Each change below is a
judgement, not an omission.

| Spec calls for | Decision | Reason |
|---|---|---|
| **FastAPI service** | **Deferred, boundary built now** | The app is local-first; nothing leaves the machine. Analytics ships as a **pure library behind a service boundary**, so the club server (`PRODUCT_VISION.md` H3) adds FastAPI over it without a rewrite. Building the API first would serve nobody. |
| **PostGIS + GeoPandas** | **Deferred** | Coordinates are already 0–100 on a 105×68 m pitch. NumPy does this in microseconds. Adopt when a spatial *query* is the bottleneck — not before. |
| **Celery / Redis / Dramatiq** | **Rejected for now** | A broker for a single-user desktop app is infrastructure for prestige. `vision_runner.py` already runs detached work with PID supervision. |
| **DuckDB / Parquet / Arrow** | **Deferred** | 223 events. Revisit at ~10⁶. |
| **Season simulation, relegation and title probability** | **Out of scope** | Requires a league. We have one youth team and six matches. |
| **Cross-league player similarity, style clustering** | **Out of scope** | Clustering a squad of fifteen produces noise with a dendrogram attached. |
| **Win probability, team strength (Elo/SPI)** | **Deferred** | Needs match volume we will not have for seasons. |
| **XGBoost / LightGBM / PyTorch** | **Deferred** | We will have dozens of shots, not 10⁵. Interpretable models only, until the data earns more. |
| **Provider adapters** | **Adopted, reframed** | Our providers are **the Ear**, **the Eye**, and **Manual Entry**. This is exactly the right abstraction and we already need it. |
| **Tracking ingestion** | **Adopted — we already have one** | The Eye *is* a tracking source. Low quality, so everything derived grades *indicative*. |
| **Metric registry, versioning, provenance, query engine** | **Adopted wholesale** | The best part of the specification and the direct fix for our 16 hard-coded strings. |
| **Possession / sequence engines** | **Adopted** | Achievable on current data and unlocks most derived metrics. |
| **Event + qualifier model** | **Adopted** | Prevents the hundreds-of-nullable-columns wall we would otherwise hit within a month. |

**Rule of thumb:** adopt every piece of the specification that is about *how to
model football*; defer every piece that is about *operating at league scale*.

---

## 4. Target architecture

Domain logic separated from delivery, as §3 requires — but delivered into a
local app rather than a service, with the boundary drawn so a service can be
added later.

```text
                    ┌──────────────────────────────────────┐
   delivery         │ Streamlit pages · report · clips     │
                    │ (later: FastAPI for the club server) │
                    └──────────────────▲───────────────────┘
                                       │  service layer
                    ┌──────────────────┴───────────────────┐
   models           │ xG · xA · xT · PV      (versioned)   │
                    └──────────────────▲───────────────────┘
                    ┌──────────────────┴───────────────────┐
   analytics        │ metric registry + query engine       │
                    │ passing · shooting · defending ·     │
                    │ pressing · spatial · physical        │
                    └──────────────────▲───────────────────┘
                    ┌──────────────────┴───────────────────┐
   football         │ possessions · sequences · zones ·    │
                    │ taxonomy · qualifiers                │
                    └──────────────────▲───────────────────┘
                    ┌──────────────────┴───────────────────┐
   ingest           │ adapters: the Ear · the Eye · manual │
                    │ normalisation · validation           │
                    └──────────────────▲───────────────────┘
                    ┌──────────────────┴───────────────────┐
   sources          │ microphone · camera · typed entry    │
                    └──────────────────────────────────────┘
```

New package layout, evolving the existing modules rather than replacing them:

```text
football/     taxonomy, qualifiers, possessions, sequences, zones
analytics/    registry, query, passing, shooting, defending, pressing, spatial
models/       xg, xa, xt, pv  (each versioned, each with a card)
ingest/       adapters (ear, eye, manual), normalisation, validation
```

`vision/` keeps the pipeline; `analytics/spatial` absorbs `vision/analytics.py`.

---

## 5. The coordinate bridge

**The single most important early decision.** Spatial analytics need x/y on every
event. Vision supplies them; the Ear does not.

Three tiers, each with declared provenance — never mixed silently:

| Tier | Source | Provenance |
|---|---|---|
| `measured` | Vision, calibrated **and** fixed camera | True pitch coordinates |
| `projected` | Vision, uncalibrated or panning | Image space; directional only |
| `zone_estimate` | A logged phrase (`"box"`, `"left wing"`) mapped to a zone centroid | Coarse — good enough for zones, never for distances |

A shot logged as "from the box" becomes a box-centroid coordinate tagged
`zone_estimate`. xG computed from it is honest at zone resolution and says so.
This is what makes the whole programme run on today's data instead of waiting
for the retrain.

---

## 6. Phases

Merges the specification's nine phases with `EYE_PLAN.md`'s ingest work.
**Phase 0 is new and comes first** — it fixes defects that corrupt everything
downstream.

### Phase 0 — Ingest correctness · *nothing is trustworthy until this lands*

From `EYE_PLAN.md`. Two live defects:

1. **Timestamps drift by the length of every stream outage.** `t_sec =
   _raw_index / fps` counts frames *received*, not time *elapsed*: a 60 s dropout
   stamps everything after it 60 s early, compounding per reconnect, and
   propagating through `bridge.py` into wall-clock stamps — so it **cuts clips in
   the wrong place**. Fix: derive time from the wall clock.
2. **A live run leaves no footage.** Only `match_stats.json` is written, so live
   matches produce numbers and nothing to clip. Fix: tee to disk, as
   `rig_capture.py` already does.

Plus live-edge discipline, source telemetry, adaptive quality, pre-roll buffer.

### Phase 1 — Foundation

Metric registry (§65) with versioned definitions (§66) and per-datum provenance
(§67). Event + qualifier model (§7). Coordinate normalisation and the bridge
above. Provider adapter protocol (§68) over the Ear, the Eye and manual entry.
Competition, Season, Player, MatchPlayer, Period. Validation and identity
resolution (§69–70). Alembic — the hand-rolled `_ADDED_COLUMNS` migration will
not survive this many tables.

### Phase 2 — Core statistics

Passing, shooting, assists, defending, duels, discipline, goalkeeping (§10–33),
all registry-driven. **No metric gets a bespoke function.**

### Phase 3 — Possessions and sequences

Reconstruction engines (§8–9), progressive actions, carries, high turnovers,
PPDA with numerator and denominator exposed (§35).

### Phase 4 — Spatial

Zones, heat maps, average positions, pass maps and networks, territory (§41–43).
Mostly promoting `vision/analytics.py` from post-hoc to first-class.

### Phase 5 — Models

xG → xGOT → xA → xT (§36–40). **Interpretable and published**: logistic
regression and a grid Markov xT, coefficients written into the repo and printed
in the report. Every model ships a card — features, sample, calibration, version,
training date. Refit against our own data as volume grows; never import a
professional model and imply it transfers to under-14s.

### Phase 6 — Tracking derivatives

Pressure, shape, compactness, defensive lines, physical output (§44–48) from the
Eye. All grade *indicative* until the retrain.

### Phase 7 — Tactical intelligence

Line breaks, off-ball runs and their value, overloads, pass-choice and expected
pass completion, formation inference (§49–56). The specification is right that
run value matters: **player value must not be restricted to touches.**

### Phase 8 — Live analytics

Incremental update rather than recomputation (§58), live xG/xT/momentum,
transparent momentum (§59), live alerts. Merges `EYE_PLAN.md` Tier 2.

### Phase 9 — Hardening

Caching, precomputation, observability, docs, metric catalogue export (§72–77,
§89). FastAPI added here **if** the club server needs it.

---

## 7. The query engine · the most important requirement

§64, adopted without reservation. Metrics are **compositions of filters over
events**, not hand-written functions:

```text
successful progressive forward passes
under high pressure into the final third
by central midfielders in the second half while drawing
```

must be expressible without a new column or a new function. This is the
difference between a platform and a pile of counters, and it is why Phase 1 comes
before Phase 2.

It is also the substrate for the natural-language layer (§87): the LLM compiles a
question into a structured query; **the engine computes the answer.** An LLM must
never calculate a statistic.

---

## 8. What we will not build

Beyond §94's list, which is adopted:

- **A single opaque player rating.** Components stay visible. On children this is
  not merely bad practice, it is indefensible.
- **Learned models on insufficient data.** No gradient boosting on fifty shots.
- **League-scale prediction** — simulation, relegation, title probability.
- **Cross-league similarity** on a fifteen-player squad.
- **Any metric without provenance**, including ones inherited from a provider.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| The spec's ambition outruns the data and everything grades *indicative* | The trust gate makes that visible rather than embarrassing; Phase 0 and the retrain are what move the needle |
| Registry indirection makes simple things hard | Registry first, then migrate the existing 16 metrics onto it as the proof |
| Migration churn across many new tables | Alembic in Phase 1, before the tables exist |
| Scope collapse under 97 sections | Phases are ordered by dependency; Phase 0–2 is the honest near-term commitment |
| One maintainer (`PRODUCT_VISION.md`) | Argues for fewer, better-founded metrics over breadth |

## 10. Open questions

1. **Does the coach ever indicate location?** A tap on a pitch diagram in Manual
   Entry would upgrade whole classes of metric from `zone_estimate` to something
   far better, at real cost to match-day speed.
2. **How many metric versions do we keep live?** §66 is right that definitions
   must be versioned; carrying every version forever has its own cost.
3. **Does the club server arrive before or after Phase 5?** It decides whether
   the service boundary is theoretical or load-bearing.
4. **What is the minimum sample before a model is shown at all?** An xG from
   twelve shots is a number, not an estimate.

---

## 11. Immediate execution order

1. **Phase 0 defects** — wall-clock time, record-while-analysing.
2. **Metric registry + provenance** — the foundation everything reads from.
3. **Migrate the existing 16 metrics onto it** — proof before expansion.
4. **Event + qualifier model, coordinate bridge.**
5. **Possession and sequence engines.**
6. Then Phase 2 breadth, registry-driven throughout.
