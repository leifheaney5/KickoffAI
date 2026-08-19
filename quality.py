#!/usr/bin/env python3
"""
Kickoff Pulse — run quality (the trust gate).

Vision numbers are only as good as the run that produced them. On the current
model and footage the Eye detects the ball in a small minority of frames, which
makes possession and passing directional rather than measured. Rather than hide
that or block on it, every run carries a `run_quality` block (written by
scripts/live_vision.py) and this module turns it into a verdict:

    measured    — trustworthy enough to state as fact and to aggregate
    indicative  — real signal, but directional; label it, don't aggregate it
    unusable    — too little data to say anything

The verdict drives how the report phrases vision stats, how heavily vision
contributes to momentum, and whether a match feeds season-level trends.

Pure functions over plain dicts — no vision or Streamlit dependencies, so this
runs anywhere (including CI) and is cheap to test.

Thresholds live here, in one place, deliberately. They are a judgement about the
*current* model; when the retrain lands, retune them here and every consumer
follows.
"""

from __future__ import annotations

MEASURED = "measured"
INDICATIVE = "indicative"
UNUSABLE = "unusable"

# Ball-detection rate is the dominant factor: possession and passing are both
# ball-dependent, so everything degrades with it. 0.35 is a starting point for
# the pre-retrain model and is expected to move.
BALL_RATE_MEASURED = 0.35
BALL_RATE_INDICATIVE = 0.10

# Below this many processed frames there simply isn't enough of a match to say
# anything, whatever the ball rate looks like on a handful of frames.
MIN_FRAMES = 200

# A run that repeatedly lost the stream has gaps in its possession clock, so it
# cannot claim to be a complete measurement of the match.
MAX_RECONNECTS_MEASURED = 10

VERDICT_LABEL = {
    MEASURED: "Measured",
    INDICATIVE: "Indicative",
    UNUSABLE: "Unusable",
}

VERDICT_BLURB = {
    MEASURED: "Vision tracked the ball well enough to state these as measured.",
    INDICATIVE: "Vision saw the ball too rarely to be exact — treat these as "
                "directional, not measured.",
    UNUSABLE: "Vision did not gather enough usable data for these figures.",
}


def run_quality_of(stats: dict) -> dict:
    """Pull the `run_quality` block out of a match_stats document."""
    block = (stats or {}).get("run_quality")
    return dict(block) if isinstance(block, dict) else {}


def assess(run_quality: dict) -> dict:
    """Judge a run. Returns {verdict, label, blurb, reasons, ...}.

    ``reasons`` explains the verdict in plain language — always populated, so a
    report or a log line can say *why* rather than just asserting a grade.
    """
    rq = run_quality or {}
    frames = int(rq.get("frames_processed", 0) or 0)
    ball = float(rq.get("ball_detection_rate", 0.0) or 0.0)
    reconnects = int(rq.get("reconnects", 0) or 0)
    calibrated = bool(rq.get("calibrated", False))

    reasons = []

    if not rq or frames < MIN_FRAMES:
        verdict = UNUSABLE
        reasons.append(
            f"only {frames} frames analysed (need {MIN_FRAMES})" if rq
            else "no vision run recorded")
    elif ball < BALL_RATE_INDICATIVE:
        verdict = UNUSABLE
        reasons.append(f"ball seen in {ball * 100:.0f}% of frames, below the "
                       f"{BALL_RATE_INDICATIVE * 100:.0f}% floor")
    elif ball < BALL_RATE_MEASURED:
        verdict = INDICATIVE
        reasons.append(f"ball seen in {ball * 100:.0f}% of frames "
                       f"(measured needs {BALL_RATE_MEASURED * 100:.0f}%)")
    elif reconnects > MAX_RECONNECTS_MEASURED:
        verdict = INDICATIVE
        reasons.append(f"stream dropped {reconnects} times, leaving gaps")
    else:
        verdict = MEASURED
        reasons.append(f"ball seen in {ball * 100:.0f}% of frames")

    # Calibration doesn't change the verdict — it changes what the numbers mean.
    # An uncalibrated run is in image space, so distances are not metric. Only
    # worth saying when a run actually happened; "uncalibrated" is meaningless
    # when there was no camera run at all.
    fixed = bool(rq.get("fixed_camera", False))
    if rq and not calibrated:
        reasons.append("uncalibrated camera, so positions are image-space")
    elif rq and calibrated and not fixed:
        # The trap worth naming: a calibration that exists but cannot hold. A
        # homography is only valid while the camera is still, so on an
        # auto-following camera it goes stale the moment play moves.
        reasons.append("calibrated, but the camera pans — the mapping goes stale, "
                       "so treat positions as image-space anyway")

    return {
        "verdict": verdict,
        "label": VERDICT_LABEL[verdict],
        "blurb": VERDICT_BLURB[verdict],
        "reasons": reasons,
        "ball_detection_rate": ball,
        "frames_processed": frames,
        "reconnects": reconnects,
        "calibrated": calibrated,
        "fps": float(rq.get("fps", 0.0) or 0.0),
    }


def assess_stats(stats: dict) -> dict:
    """Convenience: assess a whole match_stats document."""
    return assess(run_quality_of(stats))


def is_trustworthy(assessment: dict) -> bool:
    """True when a run's vision figures may be stated as measured fact."""
    return (assessment or {}).get("verdict") == MEASURED


def is_usable(assessment: dict) -> bool:
    """True when a run has enough signal to show at all (labelled if indicative)."""
    return (assessment or {}).get("verdict") in (MEASURED, INDICATIVE)


def momentum_weight(assessment: dict) -> float:
    """How heavily vision should count toward the fused momentum curve.

    A poor run should nudge the curve, not drive it — otherwise a match where
    the Eye barely saw the ball would produce confident-looking momentum built
    on noise.
    """
    return {MEASURED: 1.0, INDICATIVE: 0.4, UNUSABLE: 0.0}.get(
        (assessment or {}).get("verdict"), 0.0)


def summary_line(assessment: dict) -> str:
    """One sentence for a report or a log: the verdict and why."""
    a = assessment or {}
    label = a.get("label", "Unusable")
    reasons = "; ".join(a.get("reasons") or [])
    return f"{label} — {reasons}." if reasons else f"{label}."
