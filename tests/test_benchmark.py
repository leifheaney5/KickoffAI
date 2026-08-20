"""Tests for scripts/benchmark.py — the N-arm detection-quality comparison.

Three things here are worth more than the rest.

The output-path guard: the vision runner defaults to writing match_stats.json
and match_data.json, which are the user's real match. A benchmark that inherited
that default would overwrite a live match with test data and nothing would say
so, so the refusal is tested rather than trusted.

The timing guard: two earlier runs of this comparison were ruined by the Mac
sleeping mid-benchmark, one of them reporting 26120 seconds for a few minutes of
work. The stopwatch has to notice that and say so instead of printing a
confident wrong number.

The metrics: derived by hand from a handful of scripted frames, so the
arithmetic is checked against something other than a previous run of itself.
"""

import argparse
import importlib.util
import json
import os
import sys
import types

import pytest

# scripts/ is not a package, so load by path. Registering the module in
# sys.modules first is required for the dataclasses in it to resolve.
_SPEC = importlib.util.spec_from_file_location(
    "kickoff_benchmark",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "scripts", "benchmark.py"),
)
B = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = B
_SPEC.loader.exec_module(B)


def _args(**over):
    defaults = {
        "model": "soccer_yolov8m_v1.pt", "device": "cpu", "stride": 6,
        "conf": 0.25, "at": 0.0, "seconds": 600.0, "max_frames": 0,
        "ocr": False, "out_dir": "benchmarks", "out": "", "no_caffeinate": True,
    }
    defaults.update(over)
    return argparse.Namespace(**defaults)


def _record(players=0, ball=True, first_id=0):
    """A stand-in FrameRecord: only ball.x and player ids are ever read."""
    return types.SimpleNamespace(
        ball=types.SimpleNamespace(x=1.0 if ball else None, y=2.0),
        players=[types.SimpleNamespace(id=f"TeamA_trk{first_id + i}")
                 for i in range(players)],
    )


# --------------------------------------------------------------------------- #
# Arm specs
# --------------------------------------------------------------------------- #
def test_an_arm_is_a_video_and_an_inference_size():
    arm = B.parse_arm("/footage/match_1080p.mp4@1920")
    assert arm.video == "/footage/match_1080p.mp4"
    assert arm.imgsz == 1920
    assert arm.label == "match_1080p.mp4@1920"


def test_an_arm_can_be_labelled_for_the_table():
    arm = B.parse_arm("1080p-hi=/footage/match.mp4@1920")
    assert (arm.label, arm.video, arm.imgsz) == ("1080p-hi", "/footage/match.mp4", 1920)


def test_a_url_containing_an_at_sign_still_parses():
    """The size is always the last field, so the split is from the right."""
    arm = B.parse_arm("veo=https://user@host/feed.m3u8@960")
    assert arm.video == "https://user@host/feed.m3u8"
    assert arm.imgsz == 960


def test_a_malformed_arm_is_rejected_rather_than_guessed():
    for spec in ("/footage/match.mp4", "/footage/match.mp4@big", "@960"):
        with pytest.raises(ValueError):
            B.parse_arm(spec)


# --------------------------------------------------------------------------- #
# The output guard
# --------------------------------------------------------------------------- #
def test_real_match_files_are_refused_as_benchmark_output():
    """A benchmark must never be able to overwrite a live match."""
    for path in ("match_stats.json", "match_data.json", "control.json",
                 "/Users/x/KickoffAI/match_stats.json", "./match_data.json"):
        with pytest.raises(ValueError):
            B.refuse_protected_output(path)


def test_an_ordinary_benchmark_path_is_allowed():
    assert B.refuse_protected_output("benchmarks/arm.json") == "benchmarks/arm.json"
    # The name only collides on the basename, not on a substring of it.
    assert B.refuse_protected_output("benchmarks/match_stats_360p.json")


def test_the_pipeline_config_cannot_be_pointed_at_a_real_match():
    arm = B.parse_arm("a=/footage/m.mp4@960")
    with pytest.raises(ValueError):
        B.build_config(arm, _args(), "match_stats.json")


def test_the_pipeline_config_carries_the_arm_and_shared_settings():
    arm = B.parse_arm("a=/footage/m.mp4@1920")
    cfg = B.build_config(arm, _args(stride=4, seconds=300.0), "benchmarks/a.json")
    assert cfg.detection_imgsz == 1920
    assert cfg.frame_stride == 4
    assert cfg.max_seconds == 300.0
    assert cfg.output_path == "benchmarks/a.json"
    # OCR reads numbers off players the detector already found, so leaving it on
    # would only add a variable slice of wall clock to the throughput column.
    assert cfg.ocr_enabled is False


def test_ocr_can_be_turned_back_on_explicitly():
    arm = B.parse_arm("a=/footage/m.mp4@960")
    assert B.build_config(arm, _args(ocr=True), "benchmarks/a.json").ocr_enabled is True


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def test_metrics_are_the_arithmetic_they_claim_to_be():
    """Four frames, counted by hand.

    Ball on 3 of 4 -> 0.75. Players 4 + 2 + 0 + 0 = 6 over 4 frames -> 1.5.
    One frame has neither a ball nor a player -> blank rate 0.25. Ids trk0..trk3
    appear, and the second frame reuses trk0 and trk1 -> 4 distinct.
    """
    metrics = B.ArmMetrics()
    metrics.observe(_record(players=4, ball=True))
    metrics.observe(_record(players=2, ball=True))
    metrics.observe(_record(players=0, ball=True))
    metrics.observe(_record(players=0, ball=False))
    summary = metrics.summary()

    assert summary["frames"] == 4
    assert summary["ball_detection_rate"] == 0.75
    assert summary["players_per_frame"] == 1.5
    assert summary["blank_frame_rate"] == 0.25
    assert summary["distinct_track_ids"] == 4


def test_a_frame_with_the_ball_but_no_players_is_not_blank():
    """Blank means the detector found nothing at all, not 'found no players'."""
    metrics = B.ArmMetrics()
    metrics.observe(_record(players=0, ball=True))
    assert metrics.summary()["blank_frame_rate"] == 0.0


def test_the_ball_is_counted_only_where_it_was_actually_detected():
    """ball.status is inferred and persists across misses; ball.x does not.

    Counting status would report a far rosier rate than reality and would not be
    comparable with the live runner's own figure.
    """
    metrics = B.ArmMetrics()
    record = _record(players=1, ball=False)
    record.ball.status = "possessed_by_TeamA_No10"
    metrics.observe(record)
    assert metrics.summary()["ball_detection_rate"] == 0.0


def test_an_arm_that_produced_nothing_reports_zeros_not_a_crash():
    summary = B.ArmMetrics().summary()
    assert summary == {"frames": 0, "ball_detection_rate": 0.0,
                       "players_per_frame": 0.0, "blank_frame_rate": 0.0,
                       "distinct_track_ids": 0}


# --------------------------------------------------------------------------- #
# Timing: the failure that destroyed two earlier measurements
# --------------------------------------------------------------------------- #
def test_a_normal_run_reports_no_suspension():
    watch = B.Stopwatch().stop()
    assert watch.suspended == 0.0
    assert watch.wall >= 0.0


def test_a_sleeping_machine_is_reported_not_folded_into_the_wall_clock(monkeypatch):
    """monotonic stops while the machine is suspended; time.time does not.

    Simulated: 12 seconds of real work, 26000 seconds of the lid being shut. The
    wall clock must stay 12, and the 26000 must surface as its own figure rather
    than becoming the benchmark's headline number.
    """
    monkeypatch.setattr(B.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(B.time, "time", lambda: 1000.0)
    monkeypatch.setattr(B.time, "process_time", lambda: 10.0)
    watch = B.Stopwatch()

    monkeypatch.setattr(B.time, "monotonic", lambda: 112.0)
    monkeypatch.setattr(B.time, "time", lambda: 27012.0)
    monkeypatch.setattr(B.time, "process_time", lambda: 21.0)
    watch.stop()

    assert watch.wall == 12.0
    assert watch.calendar == 26012.0
    assert watch.cpu == 11.0
    assert watch.suspended == 26000.0
    assert watch.to_dict()["wall_seconds"] == 12.0


def test_a_clock_nudge_is_not_mistaken_for_sleep(monkeypatch):
    """NTP steps the calendar clock by a second or two; that is not a suspension."""
    monkeypatch.setattr(B.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(B.time, "time", lambda: 0.0)
    monkeypatch.setattr(B.time, "process_time", lambda: 0.0)
    watch = B.Stopwatch()

    monkeypatch.setattr(B.time, "monotonic", lambda: 60.0)
    monkeypatch.setattr(B.time, "time", lambda: 62.0)
    monkeypatch.setattr(B.time, "process_time", lambda: 55.0)
    watch.stop()

    assert watch.suspended == 0.0


def test_caffeinate_wraps_the_same_interpreter_and_arguments():
    cmd = B.caffeinate_command(["scripts/benchmark.py", "a=/v.mp4@960"])
    assert cmd[:2] == ["caffeinate", "-i"]
    assert cmd[2] == sys.executable
    assert cmd[3:] == ["scripts/benchmark.py", "a=/v.mp4@960"]


def test_the_caffeinate_wrapper_is_applied_once_not_recursively(monkeypatch):
    """The child sets the marker, so it must not re-exec itself forever."""
    monkeypatch.setattr(B.sys, "platform", "darwin")
    monkeypatch.setenv(B.CAFFEINATED_ENV, "1")
    monkeypatch.setattr(B.os, "execvp",
                        lambda *a: pytest.fail("re-exec looped"))
    B.maybe_reexec_under_caffeinate(["scripts/benchmark.py"])


def test_no_caffeinate_outside_macos(monkeypatch):
    monkeypatch.setattr(B.sys, "platform", "linux")
    monkeypatch.delenv(B.CAFFEINATED_ENV, raising=False)
    monkeypatch.setattr(B.os, "execvp", lambda *a: pytest.fail("re-exec on linux"))
    B.maybe_reexec_under_caffeinate(["scripts/benchmark.py"])


# --------------------------------------------------------------------------- #
# Running an arm
# --------------------------------------------------------------------------- #
class FakeAnalyzer:
    """Stands in for MatchAnalyzer. Building a real one loads YOLO."""

    def __init__(self, config, records=(), fail=None):
        self.config = config
        self._records = list(records)
        self._fail = fail
        self._frame_w, self._frame_h = 1920, 1080
        self.opened = None
        self.closed_with_save = None

    def open(self, source):
        self.opened = source
        if self._fail:
            raise self._fail

    def step(self):
        if not self._records:
            return None
        return (0, None, [], self._records.pop(0))

    def close(self, save=True):
        self.closed_with_save = save


def test_run_arm_measures_the_frames_the_analyzer_produced():
    arm = B.parse_arm("hi=/footage/m.mp4@1920")
    analyzer = FakeAnalyzer(None, records=[_record(players=2, ball=True),
                                           _record(players=2, ball=False)])
    result = B.run_arm(arm, _args(), analyzer_factory=lambda cfg: analyzer,
                       stats_path="benchmarks/hi.json")

    assert analyzer.opened == "/footage/m.mp4"
    assert result.metrics["frames"] == 2
    assert result.metrics["ball_detection_rate"] == 0.5
    assert result.source_width == 1920
    assert result.error == ""
    # save=False, or the pipeline writes its own document over ours.
    assert analyzer.closed_with_save is False


def test_run_arm_honours_a_hard_frame_cap():
    arm = B.parse_arm("a=/footage/m.mp4@960")
    analyzer = FakeAnalyzer(None, records=[_record() for _ in range(10)])
    result = B.run_arm(arm, _args(max_frames=3),
                       analyzer_factory=lambda cfg: analyzer)
    assert result.metrics["frames"] == 3


def test_a_failing_arm_is_recorded_rather_than_raised():
    """An unreadable video must cost that arm, not the whole comparison."""
    arm = B.parse_arm("bad=/missing.mp4@960")
    analyzer = FakeAnalyzer(None, fail=FileNotFoundError("no such file"))
    result = B.run_arm(arm, _args(), analyzer_factory=lambda cfg: analyzer)

    assert result.error == "FileNotFoundError: no such file"
    assert result.metrics["frames"] == 0
    # The capture is still released, even on the failing path.
    assert analyzer.closed_with_save is False


def test_one_broken_arm_does_not_cost_the_arms_that_worked():
    arms = [B.parse_arm("bad=/missing.mp4@960"), B.parse_arm("good=/m.mp4@960")]
    analyzers = iter([
        FakeAnalyzer(None, fail=FileNotFoundError("no such file")),
        FakeAnalyzer(None, records=[_record(players=3, ball=True)]),
    ])
    report = B.run_benchmark(arms, _args(),
                             analyzer_factory=lambda cfg: next(analyzers))

    assert report["arms"][0]["error"].startswith("FileNotFoundError")
    assert report["arms"][1]["error"] == ""
    assert report["arms"][1]["frames"] == 1


def test_the_report_records_the_settings_every_arm_shared():
    arm = B.parse_arm("a=/m.mp4@960")
    report = B.run_benchmark(
        [arm], _args(stride=4, at=600.0, seconds=300.0),
        analyzer_factory=lambda cfg: FakeAnalyzer(cfg, records=[_record()]))

    assert report["stride"] == 4 and report["at"] == 600.0
    assert report["seconds"] == 300.0
    assert report["arms"][0]["label"] == "a"
    assert report["arms"][0]["imgsz"] == 960


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #
def _report(**arm_over):
    arm = {
        "label": "1080p-hi", "video": "/m.mp4", "imgsz": 1920, "error": "",
        "frames": 1000, "ball_detection_rate": 0.332, "players_per_frame": 14.2,
        "blank_frame_rate": 0.01, "distinct_track_ids": 88,
        "wall_seconds": 612.0, "calendar_seconds": 612.0, "cpu_seconds": 590.0,
        "suspended_seconds": 0.0, "frames_per_second": 1.63,
    }
    arm.update(arm_over)
    return {"model": "m.pt", "device": "mps", "stride": 6, "conf": 0.25,
            "at": 600, "seconds": 600, "arms": [arm]}


def test_the_table_states_the_detection_rate_as_a_percentage():
    table = B.format_table(_report())
    row = [line for line in table.splitlines() if line.startswith("1080p-hi")][0]
    assert "33.2%" in row
    assert "1920" in row and "1000" in row


def test_a_failed_arm_says_so_instead_of_printing_zeros():
    table = B.format_table(_report(error="FileNotFoundError: no such file"))
    assert "failed: FileNotFoundError" in table
    assert "0.0%" not in table


def test_the_table_shouts_when_the_machine_slept_through_the_run():
    """The whole point: a wrong timing must never be printed as if it were real."""
    table = B.format_table(_report(suspended_seconds=26000.0,
                                   calendar_seconds=26612.0))
    assert "WARNING" in table
    assert "caffeinate" in table
    assert "26000s" in table


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_the_cli_refuses_to_write_over_a_real_match(capsys):
    with pytest.raises(SystemExit) as exit_info:
        B.main(["a=/m.mp4@960", "--out", "match_stats.json", "--no-caffeinate"])
    assert exit_info.value.code == 2
    assert "live match data" in capsys.readouterr().err


def test_the_cli_writes_its_report_where_it_was_told(tmp_path, monkeypatch, capsys):
    out = tmp_path / "report.json"
    monkeypatch.setattr(B, "default_analyzer",
                        lambda cfg: FakeAnalyzer(cfg, records=[
                            _record(players=2, ball=True)]))
    code = B.main(["a=/m.mp4@960", "--out", str(out),
                   "--out-dir", str(tmp_path), "--no-caffeinate"])
    capsys.readouterr()

    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["arms"][0]["frames"] == 1
    assert report["arms"][0]["ball_detection_rate"] == 1.0
