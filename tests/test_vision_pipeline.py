"""Tests for the vision pipeline stepping API and the analysis profiles.

Nothing here loads a model: the profiles are pure arithmetic over a source size,
and that arithmetic is the part that decides whether the ball is ever seen. CI
has no torch or ultralytics, so it has to stay that way.
"""

import importlib
import importlib.util
import os
import sys
import types

import numpy as np
import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


class _FakeCapture:
    def __init__(self, _source):
        self.frames = [
            np.zeros((12, 16, 3), dtype=np.uint8),
            np.ones((12, 16, 3), dtype=np.uint8),
            np.full((12, 16, 3), 2, dtype=np.uint8),
        ]
        self.i = 0
        self.released = False

    def isOpened(self):
        return True

    def get(self, prop):
        # Values match the constants defined in _fake_cv2_module below.
        return {5: 30.0, 3: 16, 4: 12}.get(prop, 0)

    def read(self):
        if self.i >= len(self.frames):
            return False, None
        frame = self.frames[self.i]
        self.i += 1
        return True, frame

    def release(self):
        self.released = True


class _FakeDetector:
    def track(self, _frame):
        from vision.detection import Detection

        return [Detection("ball", 0.9, (6, 4, 8, 6))]


def _fake_cv2_module():
    return types.SimpleNamespace(
        VideoCapture=_FakeCapture,
        CAP_PROP_FPS=5,
        CAP_PROP_FRAME_WIDTH=3,
        CAP_PROP_FRAME_HEIGHT=4,
    )


def test_match_analyzer_step_api(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "cv2", _fake_cv2_module())

    from vision import MatchAnalyzer, PipelineConfig

    cfg = PipelineConfig(
        frame_stride=2,
        max_frames_recorded=1,
        ocr_enabled=False,
        output_path=str(tmp_path / "match_stats.json"),
    )
    analyzer = MatchAnalyzer(cfg)
    analyzer.detector = _FakeDetector()

    analyzer.open(0)
    first = analyzer.step()
    second = analyzer.step()
    done = analyzer.step()
    stats = analyzer.close()

    assert first[0] == 0
    assert second[0] == 2
    assert done is None
    assert len(first[2]) == 1
    assert first[3].ball.x is not None
    # max_frames_recorded caps retained stats, but step still returns live frames.
    assert len(stats.frames) == 1
    assert os.path.exists(cfg.output_path)


# --------------------------------------------------------------------------- #
# Analysis profiles
# --------------------------------------------------------------------------- #
def _live_vision():
    """Import scripts/live_vision.py by path — `scripts` is not a package."""
    path = os.path.join(_REPO_ROOT, "scripts", "live_vision.py")
    spec = importlib.util.spec_from_file_location("live_vision_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args(**overrides):
    """A parsed-argument stand-in for build_config, with CLI defaults."""
    base = dict(model="soccer_yolov8m_v1.pt", device="cpu", profile="live",
                imgsz=None, stride=None, conf=0.25, stats="match_stats.json")
    base.update(overrides)
    return types.SimpleNamespace(**base)


def test_the_two_profiles_are_live_and_post():
    from vision.config import PROFILES, get_profile

    assert set(PROFILES) == {"live", "post"}
    live, post = get_profile("live"), get_profile("post")

    # Live is the settings that hold real time; post is the ones worth trusting.
    assert (live.detection_imgsz, live.frame_stride) == (960, 6)
    assert live.scale_to_source is False
    assert post.frame_stride == 3
    assert post.scale_to_source is True
    # The page and the report quote these, so they must not drift silently.
    assert live.expected_grade == "indicative"
    assert post.expected_grade == "measured"


def test_profile_lookup_defaults_and_normalises():
    from vision.config import DEFAULT_PROFILE, get_profile

    assert DEFAULT_PROFILE == "live"
    assert get_profile(None).name == "live"
    assert get_profile("").name == "live"
    assert get_profile("  POST ").name == "post"


def test_unknown_profile_is_rejected():
    from vision.config import get_profile

    with pytest.raises(ValueError) as exc:
        get_profile("turbo")
    assert "turbo" in str(exc.value)


@pytest.mark.parametrize("longest, expected", [
    (1920, 1920),   # 1080p: native, the arm that moved ball detection to 33%
    (3840, 1920),   # 4K: capped, not run at 4x the cost for no measured gain
    (1280, 1280),   # 720p: native
    (640, 960),     # 360p: floored, since its own size cannot find a ball
    (0, 1920),      # capture not open yet: the profile's declared size stands
])
def test_post_profile_scales_imgsz_to_the_source(longest, expected):
    from vision.config import get_profile, profile_imgsz

    assert profile_imgsz(get_profile("post"), longest) == expected


def test_live_profile_never_scales_to_the_source():
    """Live must stay at 960 whatever the footage is, or it stops being live."""
    from vision.config import get_profile, profile_imgsz

    live = get_profile("live")
    assert profile_imgsz(live, 3840) == 960
    assert profile_imgsz(live, 1920) == 960
    assert profile_imgsz(live, 0) == 960


def test_scaled_imgsz_is_a_multiple_of_the_model_stride():
    """Ultralytics rounds silently; we round first so the recorded size is real."""
    from vision.config import get_profile, profile_imgsz

    size = profile_imgsz(get_profile("post"), 1000)
    assert size % 32 == 0
    assert size >= 1000       # rounding up, so never below the source's detail


def test_the_bug_this_prevents_a_4k_source_is_not_downscaled_to_960():
    from vision.config import resolve_profile_settings

    chosen = resolve_profile_settings("post", source_longest_side=3840)

    assert chosen["detection_imgsz"] == 1920
    assert chosen["imgsz_auto"] is True


def test_explicit_settings_override_the_profile():
    from vision.config import resolve_profile_settings

    chosen = resolve_profile_settings("post", source_longest_side=3840,
                                      imgsz=1280, stride=9)

    assert chosen["detection_imgsz"] == 1280
    assert chosen["frame_stride"] == 9
    # An override is a hand-set value, so it is no longer auto-scaled.
    assert chosen["imgsz_auto"] is False
    assert chosen["profile"] == "post"


@pytest.mark.parametrize("imgsz, stride", [(None, None), (0, 0)])
def test_empty_overrides_leave_the_profile_alone(imgsz, stride):
    from vision.config import resolve_profile_settings

    chosen = resolve_profile_settings("live", source_longest_side=1920,
                                      imgsz=imgsz, stride=stride)

    assert (chosen["detection_imgsz"], chosen["frame_stride"]) == (960, 6)


def test_apply_profile_records_which_profile_ran():
    from vision import PipelineConfig

    cfg = PipelineConfig()
    cfg.apply_profile("post", source_longest_side=1920)

    assert cfg.profile == "post"
    assert cfg.detection_imgsz == 1920
    assert cfg.frame_stride == 3
    # Callable again once the capture reports a different size.
    cfg.apply_profile("post", source_longest_side=1280)
    assert cfg.detection_imgsz == 1280


def test_a_hand_built_config_has_no_profile():
    """Nothing may claim a profile it did not use."""
    from vision import PipelineConfig

    assert PipelineConfig(detection_imgsz=1920).profile == ""


# --------------------------------------------------------------------------- #
# CLI wiring (scripts/live_vision.py)
# --------------------------------------------------------------------------- #
def test_cli_defaults_to_live_with_no_sampling_overrides():
    args = _live_vision().build_parser().parse_args(["--video", "match.mp4"])

    assert args.profile == "live"
    # None, not 960/6: the profile has to be able to win.
    assert args.imgsz is None
    assert args.stride is None


def test_cli_accepts_the_post_profile_and_rejects_anything_else():
    parser = _live_vision().build_parser()

    assert parser.parse_args(["--video", "m.mp4", "--profile", "post"]).profile == "post"
    with pytest.raises(SystemExit):
        parser.parse_args(["--video", "m.mp4", "--profile", "turbo"])


def test_cli_still_honours_explicit_imgsz_and_stride():
    """Command lines written before profiles existed must behave as they did."""
    args = _live_vision().build_parser().parse_args(
        ["--video", "m.mp4", "--imgsz", "1280", "--stride", "4"])

    assert (args.imgsz, args.stride) == (1280, 4)


def test_build_config_applies_the_post_profile_at_native_resolution():
    cfg = _live_vision().build_config(_args(profile="post"),
                                      source_longest_side=1920)

    assert cfg.profile == "post"
    assert cfg.detection_imgsz == 1920
    assert cfg.frame_stride == 3


def test_build_config_lets_explicit_flags_win():
    cfg = _live_vision().build_config(_args(profile="post", imgsz=640, stride=8),
                                      source_longest_side=1920)

    assert (cfg.detection_imgsz, cfg.frame_stride) == (640, 8)


# --------------------------------------------------------------------------- #
# Runner wiring (vision_runner.build_argv, from control.json)
# --------------------------------------------------------------------------- #
@pytest.fixture
def runner_control(tmp_path, monkeypatch):
    monkeypatch.setenv("KICKOFF_CONTROL_FILE", str(tmp_path / "control.json"))
    monkeypatch.setenv("KICKOFF_VISION_STATE_FILE", str(tmp_path / "runner.json"))
    monkeypatch.chdir(tmp_path)

    import control
    import vision_runner
    importlib.reload(control)
    importlib.reload(vision_runner)
    yield control, vision_runner
    monkeypatch.undo()
    importlib.reload(control)
    importlib.reload(vision_runner)


def test_runner_sends_the_profile_instead_of_a_pinned_imgsz(runner_control):
    """The saved 960 used to beat everything; that was the silent downscale."""
    ctl, vr = runner_control
    state = ctl.load_control()
    state["feed"].update({"url": "https://veo.example/x.m3u8", "profile": "post"})

    argv = vr.build_argv(state)

    assert argv[argv.index("--profile") + 1] == "post"
    assert "--imgsz" not in argv
    assert "--stride" not in argv


def test_runner_sends_hand_set_sampling_when_it_is_declared(runner_control):
    ctl, vr = runner_control
    state = ctl.load_control()
    state["feed"].update({"url": "https://veo.example/x.m3u8",
                          "manual_sampling": True, "imgsz": 1280, "stride": 4})

    argv = vr.build_argv(state)

    assert argv[argv.index("--imgsz") + 1] == "1280"
    assert argv[argv.index("--stride") + 1] == "4"


def test_runner_tolerates_a_control_file_without_a_profile(runner_control):
    """control.json predates profiles; a missing or stale value must not block
    a match from starting."""
    ctl, vr = runner_control
    state = ctl.load_control()
    state["feed"].update({"url": "https://veo.example/x.m3u8"})

    assert vr.feed_profile(state) == "live"

    state["feed"]["profile"] = "ludicrous"
    assert vr.feed_profile(state) == "live"


# --------------------------------------------------------------------------- #
# Grade interpretation (quality.py)
# --------------------------------------------------------------------------- #
def test_quality_records_and_explains_the_profile():
    import quality

    a = quality.assess({"frames_processed": 4000, "ball_detection_rate": 0.18,
                        "calibrated": True, "fixed_camera": True,
                        "profile": "live"})

    assert a["verdict"] == quality.INDICATIVE
    assert a["profile"] == "live"
    assert any("post profile" in r for r in a["reasons"])


def test_quality_reads_an_old_stats_file_without_a_profile():
    import quality

    a = quality.assess({"frames_processed": 4000, "ball_detection_rate": 0.18})

    assert a["profile"] == ""
    assert not any("post profile" in r for r in a["reasons"])


def test_quality_does_not_nag_a_measured_run():
    import quality

    a = quality.assess({"frames_processed": 4000, "ball_detection_rate": 0.40,
                        "calibrated": True, "fixed_camera": True,
                        "profile": "post"})

    assert a["verdict"] == quality.MEASURED
    assert not any("post profile" in r for r in a["reasons"])
