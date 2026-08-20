"""Tests for scripts/footage_probe.py — the "is this camera fixed?" measurement.

The probe exists because footage titles lie: clips sold as "tactical camera"
were measured panning, and one called "Panorama" turned out to be the most
static footage in the corpus. Everything spatial downstream assumes a fixed
camera, so a probe that quietly mislabels a panning source is worse than no
probe at all.

Two kinds of test here. The classification rules are exercised on hand-written
shift lists, where every expected number is derived rather than recorded. The
measurement itself is exercised on synthetic clips built with a known,
deliberate translation, so "it measured 3 px" is checkable against the 3 px the
clip was constructed with.
"""

import importlib.util
import os
import sys

import numpy as np
import pytest

# scripts/ is not a package, so load the module by path like tests/test_features
# does for rig_capture. Registering it in sys.modules first is required: the
# dataclasses in it resolve their annotations through sys.modules at class
# creation time and raise without it.
_SPEC = importlib.util.spec_from_file_location(
    "footage_probe",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "scripts", "footage_probe.py"),
)
fp = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = fp
_SPEC.loader.exec_module(fp)

# Phase correlation is OpenCV's; CI installs opencv-python-headless so the
# measurement is genuinely checked there, and a dev box without it skips rather
# than failing the suite.
requires_cv2 = pytest.mark.skipif(
    importlib.util.find_spec("cv2") is None,
    reason="phase correlation needs OpenCV",
)


def _shifts(magnitudes, response=0.9, cut=False):
    """Shift records with a chosen magnitude, one per second."""
    return [
        fp.Shift(t=float(i + 1), dx=float(m), dy=0.0, magnitude=float(m),
                 response=response, cut=cut)
        for i, m in enumerate(magnitudes)
    ]


# --------------------------------------------------------------------------- #
# Classification — pure, hand-derived
# --------------------------------------------------------------------------- #
def test_percentile_returns_a_value_that_was_actually_measured():
    """Nearest-rank, so p90 of ten values is the ninth, not an interpolation."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert fp._percentile(values, 0.9) == 9.0
    assert fp._percentile(values, 0.0) == 1.0
    assert fp._percentile([], 0.9) == 0.0


def test_a_still_camera_is_called_fixed():
    result = fp.classify(_shifts([0.09, 0.08, 0.11, 0.10]), duration=4)
    assert result["verdict"] == fp.FIXED
    assert result["median_shift"] == pytest.approx(0.095)


def test_a_drifting_camera_is_called_near_fixed():
    """0.22 and 0.61 are real corpus figures: fixed mounts that breathe a little."""
    assert fp.classify(_shifts([0.22] * 5), duration=5)["verdict"] == fp.NEAR_FIXED
    assert fp.classify(_shifts([0.61] * 5), duration=5)["verdict"] == fp.NEAR_FIXED


def test_a_camera_that_follows_play_is_called_pans():
    """2.94 px/s is the Spain v Argentina clip that was titled 'tactical camera'."""
    result = fp.classify(_shifts([2.94] * 5), duration=5)
    assert result["verdict"] == fp.PANS


def test_the_band_boundaries_are_exclusive_on_the_upper_edge():
    """A median sitting exactly on a threshold belongs to the looser band."""
    assert fp.classify(_shifts([fp.FIXED_PX] * 3), duration=3)["verdict"] == fp.NEAR_FIXED
    assert fp.classify(_shifts([fp.NEAR_FIXED_PX] * 3), duration=3)["verdict"] == fp.PANS


def test_no_samples_reads_as_unknown_rather_than_fixed():
    """The dangerous failure: an empty measurement looking like a perfect camera."""
    result = fp.classify([], duration=60)
    assert result["verdict"] == fp.UNKNOWN
    assert result["median_shift"] == 0.0


def test_a_directed_broadcast_is_rejected_as_cut_footage():
    """A cut every five seconds is an editor, and no calibration survives one."""
    shifts = _shifts([0.2] * 48) + _shifts([50.0] * 12, response=0.01, cut=True)
    assert fp.classify(shifts, duration=60)["verdict"] == fp.CUTS


def test_one_discontinuity_in_a_long_probe_is_not_a_broadcast():
    """A dropped segment or a camera flash must not condemn good footage.

    One cut in two minutes is 0.5 a minute, under the 1.0 threshold, so the
    verdict still comes from the shifts — which say the camera never moved.
    """
    shifts = _shifts([0.2] * 119) + _shifts([80.0], response=0.02, cut=True)
    result = fp.classify(shifts, duration=120)
    assert result["verdict"] == fp.NEAR_FIXED
    assert len(result["cuts"]) == 1


def test_cuts_are_excluded_from_the_shift_statistics():
    """One 80 px cut would otherwise become this camera's 'max pan'."""
    shifts = _shifts([0.2] * 119) + _shifts([80.0], response=0.02, cut=True)
    result = fp.classify(shifts, duration=120)
    assert result["max_shift"] == pytest.approx(0.2)
    assert result["p90_shift"] == pytest.approx(0.2)


def test_cuts_with_nothing_clean_left_are_still_cuts_not_unknown():
    shifts = _shifts([60.0] * 4, response=0.01, cut=True)
    assert fp.classify(shifts, duration=4)["verdict"] == fp.CUTS


# --------------------------------------------------------------------------- #
# The result object
# --------------------------------------------------------------------------- #
def test_usable_means_one_calibration_holds_for_the_whole_match():
    for verdict, usable in ((fp.FIXED, True), (fp.NEAR_FIXED, True),
                            (fp.PANS, False), (fp.CUTS, False),
                            (fp.UNKNOWN, False)):
        result = fp.ProbeResult(source="x", label="x", verdict=verdict)
        assert result.usable is usable


def test_a_shift_converts_back_to_the_source_scale():
    """1 probe pixel is 6 source pixels at 1080p; the table has to say so."""
    result = fp.ProbeResult(source="x", label="x", width=1920, height=1080,
                            median_shift=0.5)
    assert result.median_shift_source_px == pytest.approx(3.0)
    # No frame size known -> no bogus conversion.
    assert fp.ProbeResult(source="x", label="x", median_shift=0.5).median_shift_source_px == 0.0


def test_default_label_prefers_the_youtube_id_over_the_url():
    assert fp.default_label("https://www.youtube.com/watch?v=2ZKZwKKiCL8") == "2ZKZwKKiCL8"
    assert fp.default_label("https://youtu.be/T2TAHYKo3UU") == "T2TAHYKo3UU"
    assert fp.default_label("/footage/tottenham.mp4") == "tottenham.mp4"


def test_summary_table_has_a_row_per_source_and_states_the_verdict():
    results = [
        fp.ProbeResult(source="a.mp4", label="a.mp4", samples=60,
                       verdict=fp.NEAR_FIXED, median_shift=0.22),
        fp.ProbeResult(source="b.mp4", label="b.mp4", samples=60,
                       verdict=fp.PANS, median_shift=2.94),
        fp.ProbeResult(source="c.mp4", label="c.mp4", error="could not open"),
    ]
    table = fp.format_summary(results)
    rows = [line for line in table.splitlines() if line.startswith(("a.", "b.", "c."))]
    assert len(rows) == 3
    assert "near-fixed" in rows[0] and "0.22" in rows[0]
    assert "pans" in rows[1] and "2.94" in rows[1]
    assert "error: could not open" in rows[2]


# --------------------------------------------------------------------------- #
# The measurement itself
# --------------------------------------------------------------------------- #
def _probe_frame(seed=0):
    """A pitch-like probe frame: smooth field, hard white lines to lock onto."""
    import cv2

    rng = np.random.default_rng(seed)
    img = np.full((fp.PROBE_HEIGHT, fp.PROBE_WIDTH), 60.0, dtype=np.float32)
    img += rng.normal(0, 3, img.shape).astype(np.float32)
    for x in range(20, fp.PROBE_WIDTH, 60):
        cv2.line(img, (x, 0), (x, fp.PROBE_HEIGHT), 240, 2)
    cv2.circle(img, (fp.PROBE_WIDTH // 2, fp.PROBE_HEIGHT // 2), 40, 250, 2)
    return img


@requires_cv2
def test_downscale_normalises_any_frame_into_the_probe_space():
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    small = fp.downscale(frame)
    assert small.shape == (fp.PROBE_HEIGHT, fp.PROBE_WIDTH)
    assert small.dtype == np.float32


@requires_cv2
def test_a_known_translation_is_recovered_with_its_sign():
    """The table reports content translation, so the sign has to be pinned.

    Content rolled 3 px to the right must read dx=+3, not -3. A silent sign flip
    would not change any verdict but would make every printed row a lie.
    """
    before = _probe_frame()
    after = np.roll(before, 3, axis=1)
    shift = fp.compare(before, after, t=1.0)
    assert shift.dx == pytest.approx(3.0, abs=0.05)
    assert shift.dy == pytest.approx(0.0, abs=0.05)
    assert shift.magnitude == pytest.approx(3.0, abs=0.05)
    assert shift.cut is False


@requires_cv2
def test_identical_frames_measure_no_motion_at_all():
    frame = _probe_frame()
    shift = fp.compare(frame, frame.copy(), t=1.0)
    assert shift.magnitude < fp.FIXED_PX
    assert shift.response > 0.9


@requires_cv2
def test_a_scene_change_collapses_the_response_and_is_flagged():
    """Two unrelated frames share no structure, so the peak has nowhere to land."""
    shift = fp.compare(_probe_frame(seed=1),
                       np.random.default_rng(2).normal(
                           128, 40, (fp.PROBE_HEIGHT, fp.PROBE_WIDTH)
                       ).astype(np.float32), t=1.0)
    assert shift.response < fp.CUT_RESPONSE
    assert shift.cut is True


@requires_cv2
def test_a_huge_jump_is_a_cut_even_when_the_response_is_confident():
    """The other face of a cut: two shots that correlate, but nonsensically."""
    before = _probe_frame()
    after = np.roll(before, 60, axis=1)
    shift = fp.compare(before, after, t=1.0)
    assert shift.magnitude > fp.CUT_SHIFT_PX
    assert shift.response > 0.5      # it correlated fine; it just moved absurdly
    assert shift.cut is True


# --------------------------------------------------------------------------- #
# End to end, on clips built with a known camera behaviour
# --------------------------------------------------------------------------- #
CLIP_FPS = 5
CLIP_FRAMES = 20
PAN_PX_PER_FRAME = 3


def _pitch_canvas():
    import cv2

    img = np.full((360, 640, 3), (40, 120, 40), dtype=np.uint8)
    for x in range(0, 640, 80):
        cv2.line(img, (x, 0), (x, 360), (240, 240, 240), 2)
    for y in range(0, 360, 60):
        cv2.line(img, (0, y), (640, y), (200, 200, 200), 1)
    cv2.circle(img, (320, 180), 50, (255, 255, 255), 2)
    cv2.rectangle(img, (30, 90), (110, 270), (255, 255, 255), 2)
    return img


def _write_clip(path, frames):
    """Encode a clip, or skip if this OpenCV build cannot do video I/O.

    A build without the mp4v encoder writes an empty file rather than raising,
    which would surface as a mystifying "the probe measured nothing" failure
    somewhere else entirely. Better to say what actually went wrong here.
    """
    import cv2

    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                             CLIP_FPS, (width, height))
    if not writer.isOpened():
        pytest.skip("this OpenCV build cannot encode mp4v video")
    for frame in frames:
        writer.write(frame)
    writer.release()

    capture = cv2.VideoCapture(str(path))
    try:
        readable = capture.isOpened() and capture.read()[0]
    finally:
        capture.release()
    if not readable:
        pytest.skip("this OpenCV build wrote a clip it cannot read back")
    return str(path)


@pytest.fixture
def panning_clip(tmp_path):
    """A camera sliding a fixed distance every frame across a static scene."""
    canvas = _pitch_canvas()
    frames = [canvas[40:220, i * PAN_PX_PER_FRAME:i * PAN_PX_PER_FRAME + 320].copy()
              for i in range(CLIP_FRAMES)]
    return _write_clip(tmp_path / "pan.mp4", frames)


@pytest.fixture
def fixed_clip(tmp_path):
    """A bolted-down camera: the scene never moves, only a player does."""
    import cv2

    canvas = _pitch_canvas()
    frames = []
    for i in range(CLIP_FRAMES):
        frame = canvas[40:220, 60:380].copy()
        cv2.circle(frame, (20 + i * 12, 90), 7, (0, 0, 255), -1)
        frames.append(frame)
    return _write_clip(tmp_path / "fixed.mp4", frames)


def _probe_clip(path):
    # per_second matches the clip's frame rate, so every frame is a sample and
    # the built-in per-frame translation is exactly what should be measured.
    return fp.probe(path, at=0.0, duration=CLIP_FRAMES / CLIP_FPS,
                    per_second=CLIP_FPS)


@requires_cv2
def test_a_panning_clip_measures_the_translation_it_was_built_with(panning_clip):
    result = _probe_clip(panning_clip)
    assert result.samples == CLIP_FRAMES
    assert result.median_shift == pytest.approx(PAN_PX_PER_FRAME, abs=0.1)
    assert result.verdict == fp.PANS
    assert result.usable is False
    # The camera slides right, so the content slides left. Sign, not just size.
    assert result.shifts[0].dx < 0


@requires_cv2
def test_a_fixed_clip_reads_as_fixed_despite_a_player_moving_through_it(fixed_clip):
    """The discrimination that matters: foreground motion is not camera motion."""
    result = _probe_clip(fixed_clip)
    assert result.median_shift < fp.FIXED_PX
    assert result.verdict == fp.FIXED
    assert result.usable is True
    assert result.cuts == []


@requires_cv2
def test_the_two_clips_are_separated_by_orders_of_magnitude(panning_clip, fixed_clip):
    """Not a marginal call: the gap is what makes a single threshold defensible."""
    pans = _probe_clip(panning_clip).median_shift
    fixed = _probe_clip(fixed_clip).median_shift
    assert pans > fixed * 100


@requires_cv2
def test_probe_reports_an_unopenable_source_instead_of_raising(tmp_path):
    result = fp.probe(str(tmp_path / "nope.mp4"), duration=4.0)
    assert result.samples == 0
    assert result.error
    assert result.verdict == fp.UNKNOWN


@requires_cv2
def test_the_cli_prints_a_table_and_reports_success(panning_clip, capsys):
    code = fp.main([panning_clip, "--for", "4", "--per-second", str(CLIP_FPS)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Verdict" in out and "pans" in out


@requires_cv2
def test_the_cli_can_emit_json_for_a_corpus_table(panning_clip, capsys):
    import json

    assert fp.main([panning_clip, "--for", "4", "--per-second", str(CLIP_FPS),
                    "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["verdict"] == fp.PANS
    assert payload[0]["usable"] is False


@requires_cv2
def test_the_cli_fails_when_nothing_could_be_measured(tmp_path, capsys):
    """A caller has to be able to tell a broken probe from a bad camera."""
    assert fp.main([str(tmp_path / "missing.mp4")]) == 1
    capsys.readouterr()
