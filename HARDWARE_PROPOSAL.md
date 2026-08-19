# Own the capture — a fixed-camera rig to replace Veo

**Proposal:** build our own camera rig so Kickoff Pulse owns the pipeline from
sensor to season, and stop renting the one part of it we do not control.

The obvious case is cost. That is not the real case.

---

## 1. The real argument: Veo's best feature is our worst problem

Veo's defining trick is an auto-following virtual camera — it crops and pans a
wide sensor to track play, so the output looks like a broadcast. For a coach
watching footage that is excellent. For *this* product it is the single largest
obstacle to spatial analysis, and the repo has been saying so for months in four
separate places:

> `vision/ROADMAP.md` — Phase 2 calibration: **blocked on fixed-panorama export**
> `vision/ROADMAP.md` — Panning / nonstandard pitch → **calibration fails**
> `vision/NEXT_STEPS.md` — **the panning camera breaks tracks**
> `vision/NEXT_STEPS.md` — **an auto-following camera invalidates a static homography**

A homography maps image pixels to pitch metres. It is only valid while the
camera does not move. Veo moves the camera every few seconds by design, so:

- **Calibration cannot hold.** The 4-point calibration shipped in v1.12.0 works
  and is unusable on this footage, because the mapping it computes is stale a
  moment later.
- **Positions stay in image space.** Perspective squashes depth, so heatmaps,
  distances and territory are directional rather than metric.
- **Tracks fragment.** ~75 track-ids for ~22 players. Per-player analytics — the
  whole of Horizon 3's player pathways — rests on identity that panning destroys.

**A fixed wide camera fixes all three permanently, on day one, with no model
work at all.** Calibrate once per mounting position and every frame afterwards
projects into true pitch coordinates.

## 2. It also clears both roadmap keystones

`PRODUCT_VISION.md` names two blockers that are not code. Owning the camera
clears both:

| Keystone | Why it is blocked today | With our own rig |
|---|---|---|
| **A 1080p export** for the retrain | Veo's export path is the bottleneck; the YouTube fallback is PO-token-gated at 360p | We hold the raw file. Any resolution, any frame, immediately |
| **Trustworthy vision** | Ball detection 4–12%; every run grades *indicative* | Fixed framing + full resolution + our own annotation footage |

The retrain needs annotated frames of *our* pitch. Owning capture means an
unlimited supply of exactly the footage the model needs, at the resolution it
needs, without asking a vendor for it.

## 3. And it completes the local-first story

The product's position is that nothing leaves the machine — except that today the
camera *is* a cloud vendor's device, uploading footage of children to their
servers under their retention policy. Owning capture is the difference between
"we process locally" and "the club owns the whole chain." That is the difference
a safeguarding conversation actually turns on.

---

## 4. Staged build — cheapest proof first

Deliberately staged so the expensive, fiddly work only happens after the cheap
version has proven the idea. **Do not build the panorama rig first.**

### Stage 0 — Borrow a camera, prove the thesis · ~1 weekend · ~$0–300

Mount any action camera (GoPro, Insta360, an old phone) high and wide, fixed, and
record one full match to its own card.

This alone tests the entire hypothesis:

- Does one fixed camera at 4–6 m cover the pitch at usable resolution?
- Does the 4-point calibration hold for 90 minutes?
- Do track-ids stop fragmenting?
- Does the footage produce a better annotation set than the Veo export?

If Stage 0 disappoints, stop — and we have learned that cheaply. **This stage
also delivers the 1080p file the retrain has been waiting on**, which makes it
worth doing whatever we decide about hardware.

### Stage 1 — A rig that records itself · ~$500

| Part | Approx |
|---|---|
| Raspberry Pi 5 (8 GB) | $80 |
| Wide camera module (IMX477 + wide/fisheye lens) | $120 |
| NVMe HAT + 500 GB SSD | $90 |
| USB-C PD battery (20,000 mAh+) | $60 |
| Weatherproof enclosure | $40 |
| 4 m mast or tripod clamp | $110 |
| **Total** | **~$500** |

Records to local storage on a schedule or a button press. No live streaming yet.

### Stage 2 — Live to the Eye · software only

The rig serves RTSP/HLS on the club wifi; the app consumes it exactly as it
consumes a Veo stream today. **No app changes are needed** — `feed.kind = stream`
already accepts any RTSP/HLS URL. The rig records locally *and* streams, so a
network drop costs the live view but never the footage.

### Stage 3 — Panorama, only if Stage 0 says we need it · ~$900

Two sensors stitched to ~180°, which is what Veo does and why it costs what it
does. Meaningful engineering: synchronisation, stitching, calibration across the
seam. Only worth it if one camera genuinely cannot cover the pitch.

---

## 5. Cost

| | Veo | Own rig |
|---|---|---|
| Hardware | ~$1,400 | ~$500 (Stage 1) |
| Per season | ~$900 subscription | $0 |
| Raw footage access | Export, capped | Immediate, full resolution |
| Camera motion | Auto-follow (breaks calibration) | Fixed (calibration holds) |
| Data location | Vendor cloud | The club's own storage |

Payback lands inside the first season. But cost is the least interesting column
here — the bottom two rows are the reason to do it.

## 6. Honest risks

**Match-day reliability is the whole game.** A Pi that crashes at kickoff means
no match. Mitigation: record locally first and stream second, so a failure of the
network or the app still leaves footage on the SSD. Test a full 90 minutes before
trusting it.

**One camera may not be enough.** The genuine technical risk. Veo uses two 4 K
sensors for a reason. At 4 m a single wide lens may not resolve a ball at the far
touchline — which is exactly what Stage 0 exists to find out before we spend.

**Power for two hours** in cold weather, with a Pi 5 that wants 5 V/5 A.
Measure it; do not assume.

**Setup time.** A coach has ten minutes before kickoff. If the rig takes twenty,
it will not get used. Mount, power, one button.

**Weather and mounting.** A 4 m mast in wind, near children. Needs to be genuinely
secure, not merely upright.

**Somebody has to maintain it.** This adds hardware to a project already carried
by one person — the same sustainability question `PRODUCT_VISION.md` raises about
the software.

## 7. What we are not proposing

- **Not a product.** Building rigs for other clubs is a hardware business with
  support obligations, and a different company to the one this is.
- **Not replacing Veo for viewing.** Their auto-follow output is genuinely better
  to *watch*. If a club wants both, both can run — our rig is for analysis.
- **Not Stage 3 first.** Panorama stitching is the interesting engineering
  problem and therefore the most tempting mistake.

## 8. Recommendation

**Do Stage 0 now.** It costs a weekend and possibly nothing at all, it tests every
assumption this proposal rests on, and it produces the 1080p footage the retrain
has been blocked on since June. Whatever we conclude about owning hardware, that
file unblocks the roadmap's single highest-leverage task.

Decide Stages 1–3 on what Stage 0 shows.
