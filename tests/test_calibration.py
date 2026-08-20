#!/usr/bin/env python3
"""Tests for the pitch calibration chain: picked points -> homography -> metres.

This is the path that turns frame pixels into pitch coordinates, and until
v1.24.0 nothing exercised it end to end -- so every run this project has ever
done reported "image" space and no test noticed.
"""

import importlib.util

import numpy as np
import pytest

from vision import calibration as vcal

# Building the matrix goes through cv2.getPerspectiveTransform. CI installs
# opencv-python-headless so the geometry is genuinely checked there; a dev box
# without OpenCV skips these rather than failing the whole suite.
requires_cv2 = pytest.mark.skipif(
    importlib.util.find_spec("cv2") is None,
    reason="homography maths needs OpenCV",
)


# A sideline camera sees the pitch as a trapezoid: the far touchline is
# foreshortened into fewer pixels than the near one. Corners in image pixels,
# paired with their normalised 0..100 pitch positions.
SIDELINE = [
    {"label": "Top-left corner",     "px": [200.0, 100.0],  "norm": [0.0, 0.0]},
    {"label": "Top-right corner",    "px": [800.0, 100.0],  "norm": [100.0, 0.0]},
    {"label": "Bottom-right corner", "px": [1000.0, 500.0], "norm": [100.0, 100.0]},
    {"label": "Bottom-left corner",  "px": [0.0, 500.0],    "norm": [0.0, 100.0]},
]


def _norm(H, x, y):
    metres = H.to_metres(np.array([(float(x), float(y))], dtype=float))
    return H.metres_to_normalised(metres)[0]


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_validate_rejects_too_few_points():
    assert "at least 4" in vcal.validate_points(SIDELINE[:3])


def test_validate_rejects_a_landmark_used_twice():
    dupe = SIDELINE[:3] + [dict(SIDELINE[0], px=[10.0, 10.0])]
    assert vcal.validate_points(dupe) == "Each landmark may only be used once."


def test_validate_rejects_collinear_points():
    """Four points along one touchline cannot define a perspective transform."""
    flat = [
        dict(p, px=[float(i * 100), 100.0]) for i, p in enumerate(SIDELINE)
    ]
    assert "collinear" in vcal.validate_points(flat)


def test_validate_accepts_a_usable_set():
    assert vcal.validate_points(SIDELINE) is None


# --------------------------------------------------------------------------- #
# The homography itself
# --------------------------------------------------------------------------- #
@requires_cv2
def test_corners_map_to_the_corners():
    H = vcal.homography_from_calibration({"points": SIDELINE})
    for pt in SIDELINE:
        assert _norm(H, *pt["px"]) == pytest.approx(pt["norm"], abs=1e-6)


@requires_cv2
def test_pitch_centre_line_is_recovered_at_every_image_height():
    """The strongest perspective check available without ground truth.

    The trapezoid is symmetric about image x=500, so every pixel on that column
    lies on the pitch's halfway line whatever its height. An affine fit or a
    transposed matrix would break this.
    """
    H = vcal.homography_from_calibration({"points": SIDELINE})
    for image_y in (100, 200, 300, 400, 500):
        assert _norm(H, 500, image_y)[0] == pytest.approx(50.0, abs=1e-6)


@requires_cv2
def test_foreshortening_is_applied_not_ignored():
    """Half way down the image is well past half way across the pitch.

    The far half of the pitch is squeezed into fewer pixels, so image mid-height
    must map beyond 50. A linear stretch would return exactly 50 and would look
    plausible on a heatmap while being wrong by 12 metres.
    """
    H = vcal.homography_from_calibration({"points": SIDELINE})
    assert _norm(H, 500, 300)[1] == pytest.approx(62.5, abs=1e-6)


@requires_cv2
def test_metres_use_the_declared_pitch_dimensions():
    H = vcal.homography_from_calibration(
        {"points": SIDELINE}, pitch_length_m=64.0, pitch_width_m=46.0
    )
    metres = H.to_metres(np.array([[1000.0, 500.0]], dtype=float))[0]
    assert metres == pytest.approx([64.0, 46.0], abs=1e-6)


@requires_cv2
def test_youth_pitch_metres_differ_from_full_size_for_the_same_pixel():
    """A youth pitch is ~64x46, not 105x68; the declared size has to matter."""
    px = np.array([[500.0, 300.0]], dtype=float)
    full = vcal.homography_from_calibration({"points": SIDELINE}).to_metres(px)[0]
    youth = vcal.homography_from_calibration(
        {"points": SIDELINE}, pitch_length_m=64.0, pitch_width_m=46.0
    ).to_metres(px)[0]
    assert full[0] > youth[0]
    # ...but the normalised position is identical, because it is size-agnostic.
    assert full[0] / 105.0 == pytest.approx(youth[0] / 64.0, abs=1e-9)


@requires_cv2
def test_more_than_four_points_are_fitted_robustly():
    extra = SIDELINE + [
        {"label": "Centre spot", "px": [500.0, 259.0], "norm": [50.0, 50.0]},
    ]
    H = vcal.homography_from_calibration({"points": extra})
    assert _norm(H, 500, 100)[0] == pytest.approx(50.0, abs=0.5)


def test_a_bad_calibration_raises_rather_than_returning_nonsense():
    with pytest.raises(ValueError):
        vcal.homography_from_calibration({"points": SIDELINE[:3]})


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
@requires_cv2
def test_save_load_round_trip_rebuilds_an_identical_homography(tmp_path):
    path = str(tmp_path / "calibration.json")
    vcal.save_calibration(SIDELINE, frame_size=(1000, 600), path=path,
                          source="fixed camera")
    cal = vcal.load_calibration(path)
    assert cal is not None
    H = vcal.homography_from_calibration(cal)
    assert _norm(H, 500, 300)[1] == pytest.approx(62.5, abs=1e-6)


def test_load_returns_none_for_absent_or_junk_files(tmp_path):
    assert vcal.load_calibration(str(tmp_path / "nope.json")) is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert vcal.load_calibration(str(bad)) is None
    empty = tmp_path / "empty.json"
    empty.write_text('{"points": []}', encoding="utf-8")
    assert vcal.load_calibration(str(empty)) is None


def test_clear_calibration_reports_whether_it_removed_anything(tmp_path):
    path = str(tmp_path / "calibration.json")
    vcal.save_calibration(SIDELINE, path=path)
    assert vcal.clear_calibration(path) is True
    assert vcal.clear_calibration(path) is False


# --------------------------------------------------------------------------- #
# Wiring: the live runner must actually use a saved calibration
# --------------------------------------------------------------------------- #
def test_live_runner_loads_the_calibration_for_a_fixed_camera():
    """--fixed-camera was parsed and reported but never applied until v1.24.0.

    The analyzer was built as MatchAnalyzer(cfg) with no homography, so a live
    run reported image space however carefully the pitch had been calibrated.
    """
    src = (vcal.__file__.rsplit("/vision/", 1)[0] + "/scripts/live_vision.py")
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    assert "homography=homography" in text, "analyzer must receive the homography"
    assert "load_calibration()" in text, "runner must load the saved calibration"
