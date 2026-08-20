#!/usr/bin/env python3
"""Tests for the pitch calibration chain: picked points -> homography -> metres.

This is the path that turns frame pixels into pitch coordinates, and until
v1.24.0 nothing exercised it end to end -- so every run this project has ever
done reported "image" space and no test noticed.
"""

import importlib.util
import json
import types

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


# --------------------------------------------------------------------------- #
# The join: does the pipeline actually use the homography it was handed?
#
# The maths above is correct and the analytics above it are tested, but nothing
# proved the two were connected. _project is the single point where pixels
# become pitch coordinates, so it is where a calibration silently going unused
# would show up -- which is exactly the shape of the --fixed-camera bug.
# --------------------------------------------------------------------------- #
def _analyzer(homography, frame_w=1000, frame_h=600):
    """A stand-in with just the attributes _project touches.

    Constructing a real MatchAnalyzer loads the YOLO detector, which is far too
    heavy for a unit test and unavailable in CI.
    """
    from vision.config import PipelineConfig
    from vision.pipeline import MatchAnalyzer

    stub = types.SimpleNamespace(
        homography=homography, _frame_w=frame_w, _frame_h=frame_h,
        config=PipelineConfig(),
    )
    return lambda pts: MatchAnalyzer._project(stub, pts)


@requires_cv2
def test_project_uses_the_homography_when_one_is_present():
    H = vcal.homography_from_calibration({"points": SIDELINE})
    metres, norm = _analyzer(H)([(500.0, 300.0)])
    assert norm[0] == pytest.approx([50.0, 62.5], abs=1e-3)
    assert metres[0] == pytest.approx([52.5, 42.5], abs=1e-3)


def test_project_falls_back_to_image_space_without_a_calibration():
    metres, norm = _analyzer(None)([(500.0, 300.0)])
    # Straight pixel scaling: 500/1000 and 300/600, perspective uncorrected.
    assert norm[0] == pytest.approx([50.0, 50.0], abs=1e-3)


@requires_cv2
def test_the_uncalibrated_fallback_is_wrong_by_metres_not_rounding():
    """Quantifies what calibration actually buys, so it is not a matter of faith.

    Same pixel, same frame. Uncalibrated says the player is on the halfway line
    across the pitch's width; calibrated knows the far half is squeezed into
    fewer pixels and puts them 8.5 m nearer the far touchline.
    """
    H = vcal.homography_from_calibration({"points": SIDELINE})
    calibrated, _ = _analyzer(H)([(500.0, 300.0)])
    uncalibrated, _ = _analyzer(None)([(500.0, 300.0)])
    error_m = abs(float(calibrated[0][1]) - float(uncalibrated[0][1]))
    assert error_m == pytest.approx(8.5, abs=0.1)


def test_project_returns_empty_pairs_for_no_points():
    metres, norm = _analyzer(None)([])
    assert metres.shape == (0, 2) and norm.shape == (0, 2)


@requires_cv2
def test_project_preserves_input_order_and_length():
    H = vcal.homography_from_calibration({"points": SIDELINE})
    pts = [(200.0, 100.0), (1000.0, 500.0), (500.0, 300.0)]
    metres, norm = _analyzer(H)(pts)
    assert len(metres) == len(norm) == 3
    assert norm[0] == pytest.approx([0.0, 0.0], abs=1e-3)
    assert norm[1] == pytest.approx([100.0, 100.0], abs=1e-3)


# --------------------------------------------------------------------------- #
# A second camera: the elevated tactical view of half a pitch
#
# The SIDELINE fixture above is a symmetric trapezoid, which is a convenient
# shape and not the one a real tactical camera produces. This one is a genuine
# pinhole projection of the ground plane, with the numbers stated below rather
# than measured off a still.
#
# HONESTY NOTE. A real reference frame (a LaLiga tactical camera, near-static at
# 0.22 px median shift) was inspected while writing this. Its landmarks cannot
# be pinned down better than about +/- 2 px on a 640x360 probe of a 1080p
# source, and one of the four penalty-area corners is out of shot, so eyeballed
# pixel coordinates would have been guesses wearing the costume of measurements
# -- and every "expected" value derived from them would have had to be captured
# from a run rather than computed. The geometry here is therefore synthetic and
# exact. What it does NOT establish is that a real camera matches this model;
# see docs/SPATIAL_VALIDATION.md.
# --------------------------------------------------------------------------- #
PITCH_L_M, PITCH_W_M = 105.0, 68.0

# Camera: 24 m up, 20 m back from the near touchline (y = 68 m), standing level
# with the right-hand penalty box rather than the halfway line. No pan, no roll,
# tilted down by 36.87 degrees -- the 3-4-5 angle, so sin/cos stay exact in
# binary floating point and the algebra below can be checked with a pencil.
CAM_X_M, CAM_Y_M, CAM_Z_M = 84.0, 88.0, 24.0
TILT_SIN, TILT_COS = 0.6, 0.8
FOCAL_PX, PRINCIPAL_X, PRINCIPAL_Y = 1200.0, 960.0, 540.0
FRAME_W, FRAME_H = 1920, 1080


def project(x_m, y_m):
    """Where a point on the pitch lands in the frame, from first principles.

    An independent oracle: plain trigonometry, no OpenCV and no homography in
    it, so when the calibration chain reproduces its landmarks the two agree by
    construction rather than by both being wrong the same way.

        depth  = (cam_y - y) * cos(tilt) + cam_z * sin(tilt)
        height = (cam_y - y) * sin(tilt) - cam_z * cos(tilt)
        pixel  = principal + focal * (offset / depth)

    Depth and height depend only on ``y``, the across-pitch coordinate, so a row
    of this image is a line of constant pitch width. That is a property of an
    unpanned, unrolled camera, not of pitches in general.
    """
    depth = (CAM_Y_M - y_m) * TILT_COS + CAM_Z_M * TILT_SIN
    height = (CAM_Y_M - y_m) * TILT_SIN - CAM_Z_M * TILT_COS
    return [
        PRINCIPAL_X + FOCAL_PX * (x_m - CAM_X_M) / depth,
        PRINCIPAL_Y - FOCAL_PX * height / depth,
    ]


def to_norm(x_m, y_m):
    return [x_m / PITCH_L_M * 100.0, y_m / PITCH_W_M * 100.0]


# Standard markings on a 105 x 68 m pitch: penalty area 16.5 m deep and 40.32 m
# wide, goal area 5.5 m deep and 18.32 m wide, penalty spot 11 m out.
PA_TOP_M, PA_BOT_M = (68.0 - 40.32) / 2, (68.0 + 40.32) / 2      # 13.84, 54.16
GA_TOP_M, GA_BOT_M = (68.0 - 18.32) / 2, (68.0 + 18.32) / 2      # 24.84, 43.16

TACTICAL_FIXTURE = (
    vcal.__file__.rsplit("/vision/", 1)[0]
    + "/tests/fixtures/tactical_camera_calibration.json"
)

# The four points the user actually clicks. They have to be entries in
# vcal.LANDMARKS -- the picker offers nothing else -- and they have to be in
# shot, which on a half-pitch view rules most of that list out.
TACTICAL_PICKS = [
    ("Right box front x top", 105.0 - 16.5, PA_TOP_M),
    ("Top-right corner", 105.0, 0.0),
    ("Bottom-right corner", 105.0, 68.0),
    ("Right box front x bottom", 105.0 - 16.5, PA_BOT_M),
]


def _tactical_cal():
    with open(TACTICAL_FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def _tactical_h():
    return vcal.homography_from_calibration(_tactical_cal())


def _recovered(H, x_m, y_m):
    """Project a landmark with the oracle, then read it back through the fit."""
    return H.metres_to_normalised(H.to_metres(np.array([project(x_m, y_m)])))[0]


# --------------------------------------------------------------------------- #
# The fixture file itself
# --------------------------------------------------------------------------- #
def test_the_checked_in_fixture_still_matches_the_camera_it_documents():
    """Guards the one thing a data file cannot say for itself.

    The pixel coordinates in the JSON are only meaningful as the projection of
    named landmarks through the stated camera. If either drifts, everything
    built on the file quietly starts measuring a different pitch.
    """
    cal = _tactical_cal()
    assert cal["frame_size"] == [FRAME_W, FRAME_H]
    assert "SYNTHETIC" in cal["source"]
    assert [p["label"] for p in cal["points"]] == [p[0] for p in TACTICAL_PICKS]
    for point, (_label, x_m, y_m) in zip(cal["points"], TACTICAL_PICKS):
        assert point["px"] == pytest.approx(project(x_m, y_m), abs=1e-9)
        assert point["norm"] == pytest.approx(to_norm(x_m, y_m), abs=1e-9)
        assert point["norm"] == pytest.approx(vcal.LANDMARKS[point["label"]], abs=1e-9)


def test_every_picked_point_is_inside_the_frame():
    for point in _tactical_cal()["points"]:
        px, py = point["px"]
        assert 0 <= px < FRAME_W and 0 <= py < FRAME_H


def test_the_fixture_is_a_pick_set_the_app_would_accept():
    assert vcal.validate_points(_tactical_cal()["points"]) is None


def test_half_the_named_landmarks_are_out_of_shot_on_this_camera():
    """Why a half-pitch calibration quad is small, and the far end guesswork.

    The near end of the halfway line sits at image x = -283: real, marked, and
    unclickable. So are both left-hand corners. A tactical camera can only be
    calibrated on the end it is pointed at.
    """
    assert project(52.5, 68.0)[0] == pytest.approx(-283.4210526, abs=1e-6)
    assert project(0.0, 0.0)[0] < 0
    assert project(0.0, 68.0)[0] < 0
    # ...while the far end of the same line is comfortably in shot.
    assert project(52.5, 0.0)[0] == pytest.approx(514.2452830, abs=1e-6)


# --------------------------------------------------------------------------- #
# Does the calibration chain reproduce the camera?
# --------------------------------------------------------------------------- #
@requires_cv2
def test_the_picked_corners_come_back_as_themselves():
    H = _tactical_h()
    for point in _tactical_cal()["points"]:
        got = H.metres_to_normalised(H.to_metres(np.array([point["px"]])))[0]
        assert got == pytest.approx(point["norm"], abs=1e-4)


@requires_cv2
def test_landmarks_it_was_not_calibrated_on_are_recovered():
    """The real check: four points fit, and the rest of the box falls out right.

    None of these were given to the fit. Their pitch positions are standard
    markings and their pixel positions come from the trigonometry above, so both
    sides of the assertion are known before OpenCV is asked anything.
    """
    H = _tactical_h()
    for x_m, y_m in [
        (94.0, 34.0),               # penalty spot, 11 m out
        (88.5, 34.0),               # apex of the D
        (105.0 - 5.5, GA_TOP_M),    # six-yard box, far side
        (105.0 - 5.5, GA_BOT_M),    # six-yard box, near side
        (105.0, 34.0),              # centre of the goal line
    ]:
        assert _recovered(H, x_m, y_m) == pytest.approx(to_norm(x_m, y_m), abs=1e-3)


@requires_cv2
def test_it_extrapolates_to_the_far_half_it_never_saw_calibrated():
    """A homography is exact everywhere or nowhere; there is no near-field fit.

    The centre spot is most of a pitch away from every picked point and still
    lands on (50, 50). Worth pinning down because it is easy to assume the
    opposite, and because it means extrapolation error, where it appears, comes
    from the clicks and not from the algebra. See the next test.
    """
    H = _tactical_h()
    assert _recovered(H, 52.5, 34.0) == pytest.approx([50.0, 50.0], abs=1e-3)
    assert _recovered(H, 52.5, 0.0) == pytest.approx([50.0, 0.0], abs=1e-3)


@requires_cv2
def test_a_two_pixel_slip_costs_centimetres_in_the_box_and_metres_upfield():
    """What a shaky click actually buys you, measured rather than assumed.

    Nudging one picked corner down two pixels -- less than a fingertip on a
    1080p still -- leaves the penalty spot within a quarter of a metre and puts
    the opposite corner of the pitch out by several. The ordering is the point:
    accuracy is bought where you calibrate and spent everywhere else, so a
    half-pitch calibration must not be trusted at the far end.
    """
    cal = _tactical_cal()
    cal["points"][0]["px"][1] += 2.0
    H = vcal.homography_from_calibration(cal)

    def error_m(x_m, y_m):
        metres = H.to_metres(np.array([project(x_m, y_m)]))[0]
        return float(np.hypot(metres[0] - x_m, metres[1] - y_m))

    in_box = error_m(94.0, 34.0)
    midfield = error_m(52.5, 34.0)
    far_end = error_m(0.0, 0.0)
    assert in_box < midfield < far_end
    assert in_box < 0.25
    assert far_end > 5.0


# --------------------------------------------------------------------------- #
# What the perspective is actually doing
# --------------------------------------------------------------------------- #
@requires_cv2
def test_the_row_midway_between_the_touchlines_is_not_midway_across_the_pitch():
    """The foreshortening check, with the answer derived rather than observed.

    The touchlines sit at rows 3420/53 and 15660/19, so the row exactly between
    them is 447480/1007. Substituting that back into the projection and solving
    for y gives 901/18 m, which on a 68 m pitch is 1325/18 = 73.61 -- most of
    the way to the near touchline, not half. An affine fit would answer 50 and
    be wrong by 16 metres in the middle of the pitch.
    """
    far_row = project(52.5, 0.0)[1]
    near_row = project(52.5, 68.0)[1]
    assert far_row == pytest.approx(3420 / 53, abs=1e-9)
    assert near_row == pytest.approx(15660 / 19, abs=1e-9)

    H = _tactical_h()
    mid_row = (far_row + near_row) / 2
    got = H.metres_to_normalised(H.to_metres(np.array([[700.0, mid_row]])))[0]
    assert got[1] == pytest.approx(1325 / 18, abs=1e-3)


@requires_cv2
def test_the_same_ten_pixels_is_two_and_a_half_times_wider_upfield():
    """Why an uncalibrated heatmap flatters the far side of the pitch.

    Ground scale is depth/focal metres per pixel. Solving the projection for the
    depth at each row gives 78.26087 m at row 100 and 31.03448 m at row 800, so
    ten pixels spans 10*78.26087/1200 = 0.652174 m up there and
    10*31.03448/1200 = 0.258621 m down here. Identical on screen, 2.5x apart on
    the grass.
    """
    H = _tactical_h()

    def span(row):
        a, b = H.to_metres(np.array([[900.0, row], [910.0, row]]))
        return float(np.hypot(b[0] - a[0], b[1] - a[1]))

    assert span(100.0) == pytest.approx(10 * 78.26087 / 1200, abs=1e-4)
    assert span(800.0) == pytest.approx(10 * 31.03448 / 1200, abs=1e-4)


@requires_cv2
def test_uncalibrated_this_camera_misplaces_the_centre_spot_by_36_metres():
    """The cost of never having calibrated, in the units a coach would use.

    The centre spot lands at pixel (303.75, 265). Divided by the frame size that
    reads as (15.82, 24.54) on the tactical map: 30375/1920 and 26500/1080. It
    is (50, 50). The error is 36 m along the pitch and 17 m across -- not a
    rounding difference, a different part of the pitch.
    """
    px = project(52.5, 34.0)
    assert px == pytest.approx([303.75, 265.0], abs=1e-9)

    _m, naive = _analyzer(None, FRAME_W, FRAME_H)([px])
    assert naive[0] == pytest.approx([30375 / 1920, 26500 / 1080], abs=1e-4)

    calibrated, _n = _analyzer(_tactical_h(), FRAME_W, FRAME_H)([px])
    assert calibrated[0] == pytest.approx([52.5, 34.0], abs=1e-3)

    naive_m = np.array(naive[0]) * np.array([PITCH_L_M, PITCH_W_M]) / 100.0
    assert abs(naive_m[0] - 52.5) == pytest.approx(35.9, abs=0.1)
    assert abs(naive_m[1] - 34.0) == pytest.approx(17.3, abs=0.1)


@requires_cv2
def test_a_fifth_point_across_the_pitch_still_fits():
    """The >4-point RANSAC branch, fed a point far from the other four.

    The centre spot is the one landmark on the far side of this view that is
    both named and visible, so it is the realistic fifth pick.
    """
    cal = _tactical_cal()
    cal["points"].append({
        "label": "Centre spot",
        "norm": [50.0, 50.0],
        "px": project(52.5, 34.0),
    })
    H = vcal.homography_from_calibration(cal)
    assert _recovered(H, 94.0, 34.0) == pytest.approx([89.5238, 50.0], abs=0.05)
    assert _recovered(H, 52.5, 34.0) == pytest.approx([50.0, 50.0], abs=0.05)
