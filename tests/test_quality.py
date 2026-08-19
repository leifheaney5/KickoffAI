"""Tests for the trust gate: run quality, momentum weighting, vision fusion.

Pure-logic tests — no vision or Streamlit dependencies, so they run on CI where
cv2/torch/matplotlib are not installed.
"""

import insights as IN
import quality as Q
import season


def rq(**over):
    """A run_quality block that grades `measured` unless overridden."""
    base = {"frames_processed": 5000, "ball_detection_rate": 0.55, "fps": 14.0,
            "reconnects": 0, "calibrated": True}
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# Verdicts
# --------------------------------------------------------------------------- #
def test_a_good_run_is_measured():
    a = Q.assess(rq())

    assert a["verdict"] == Q.MEASURED
    assert Q.is_trustworthy(a) is True
    assert Q.momentum_weight(a) == 1.0


def test_a_sparse_ball_run_is_indicative_not_measured():
    """The current model's ball rate is the whole reason this gate exists."""
    a = Q.assess(rq(ball_detection_rate=0.18))

    assert a["verdict"] == Q.INDICATIVE
    assert Q.is_trustworthy(a) is False
    assert Q.is_usable(a) is True           # still worth showing, labelled
    assert 0 < Q.momentum_weight(a) < 1.0
    assert "18%" in " ".join(a["reasons"])


def test_a_nearly_blind_run_is_unusable():
    a = Q.assess(rq(ball_detection_rate=0.04))

    assert a["verdict"] == Q.UNUSABLE
    assert Q.is_usable(a) is False
    assert Q.momentum_weight(a) == 0.0


def test_too_few_frames_is_unusable_whatever_the_ball_rate():
    """A handful of lucky frames must not grade as a measured match."""
    a = Q.assess(rq(frames_processed=50, ball_detection_rate=0.9))

    assert a["verdict"] == Q.UNUSABLE
    assert "50 frames" in " ".join(a["reasons"])


def test_a_flaky_stream_cannot_be_measured():
    """Repeated drops leave gaps in the possession clock."""
    a = Q.assess(rq(reconnects=Q.MAX_RECONNECTS_MEASURED + 1))

    assert a["verdict"] == Q.INDICATIVE
    assert "dropped" in " ".join(a["reasons"])


def test_no_run_at_all_is_unusable_and_says_so_plainly():
    a = Q.assess({})

    assert a["verdict"] == Q.UNUSABLE
    assert "no vision run recorded" in " ".join(a["reasons"])
    # "uncalibrated" is meaningless when nothing ran; it must not appear.
    assert not any("uncalibrated" in r for r in a["reasons"])


def test_calibration_is_reported_but_does_not_change_the_verdict():
    calibrated = Q.assess(rq(calibrated=True))
    uncalibrated = Q.assess(rq(calibrated=False))

    assert calibrated["verdict"] == uncalibrated["verdict"] == Q.MEASURED
    assert any("uncalibrated" in r for r in uncalibrated["reasons"])
    assert not any("uncalibrated" in r for r in calibrated["reasons"])


def test_assess_stats_reads_a_whole_document():
    a = Q.assess_stats({"run_quality": rq(), "statistical_events": {}})

    assert a["verdict"] == Q.MEASURED
    assert Q.summary_line(a).startswith("Measured")


# --------------------------------------------------------------------------- #
# Momentum fusion
# --------------------------------------------------------------------------- #
def _events():
    """One audio goal for Home, then an Away passing passage seen by the camera.

    The passes sit seconds apart, as a real passage does — vision_pressure's
    default window is minutes, so minute-spaced passes would not register.
    """
    ev = [{"match_time": "10:00", "team": "Home", "action": "goal",
           "result": "scored", "status": "approved"}]
    ev += [{"match_time": f"20:{i * 10:02d}", "team": "Away", "action": "pass",
            "result": "complete", "status": "approved", "source": "vision"}
           for i in range(9)]
    return ev


def test_vision_weight_scales_camera_events_only():
    full = IN.momentum_series(_events(), vision_weight=1.0)
    none = IN.momentum_series(_events(), vision_weight=0.0)

    # The audio goal lands identically either way...
    assert full[0]["momentum"] == none[0]["momentum"]
    # ...but the Away vision passes only pull the curve toward Away (negative)
    # when they are actually counted.
    assert full[-1]["momentum"] < none[-1]["momentum"]


def test_zero_weight_makes_the_curve_audio_only():
    audio_only = [e for e in _events() if e.get("source") != "vision"]

    assert (IN.momentum_series(_events(), vision_weight=0.0)[0]["momentum"]
            == IN.momentum_series(audio_only)[0]["momentum"])


def test_event_source_defaults_to_audio():
    assert IN.event_source({"action": "goal"}) == "audio"
    assert IN.event_source({"action": "pass", "source": "vision"}) == "vision"


# --------------------------------------------------------------------------- #
# Key moments
# --------------------------------------------------------------------------- #
def test_vision_pressure_finds_a_passing_passage():
    passages = IN.vision_pressure(_events())

    assert passages
    assert passages[0]["team"] == "Away"
    assert passages[0]["passes"] >= 6


def test_vision_pressure_ignores_audio_passes():
    """Only the camera's own passes count — this is the Eye's independent read."""
    audio_passes = [{"match_time": f"20:{i * 10:02d}", "team": "Away",
                     "action": "pass", "status": "approved"} for i in range(9)]

    assert IN.vision_pressure(audio_passes) == []


def test_vision_pressure_ignores_scattered_passes():
    """Passes spread across the match are not a passage of control."""
    scattered = [{"match_time": f"{10 + i * 5}:00", "team": "Away",
                  "action": "pass", "status": "approved", "source": "vision"}
                 for i in range(9)]

    assert IN.vision_pressure(scattered) == []


def test_key_moments_tag_their_source_and_confirmation():
    moments = IN.key_moments(_events(), vision_weight=1.0)

    assert moments
    assert all("source" in m and "confirmed" in m for m in moments)
    assert {m["source"] for m in moments} <= {"audio", "momentum", "vision"}


def test_key_moments_drop_vision_when_the_run_is_unusable():
    """A run the gate graded unusable must add no camera moments at all."""
    with_vision = IN.key_moments(_events(), vision_weight=1.0)
    without = IN.key_moments(_events(), vision_weight=0.0)

    assert any(m["source"] == "vision" for m in with_vision)
    assert not any(m["source"] == "vision" for m in without)


def test_cross_source_confirmation_marks_agreement():
    """A moment both ingests flag for the same team, close in time, is confirmed."""
    ev = [{"match_time": "20:00", "team": "Away", "action": "goal",
           "result": "scored", "status": "approved"}]
    ev += [{"match_time": "20:30", "team": "Away", "action": "pass",
            "result": "complete", "status": "approved", "source": "vision"}
           for _ in range(8)]

    moments = IN.key_moments(ev, vision_weight=1.0)
    goal = next(m for m in moments if m["type"] == "goal")

    assert goal["confirmed"] is True


# --------------------------------------------------------------------------- #
# Season aggregation
# --------------------------------------------------------------------------- #
def _match(verdict, hp=60.0, ap=40.0, **over):
    m = {"played_on": "2026-08-01", "home_team": "Eagles", "away_team": "Hawks",
         "vision_verdict": verdict, "vision_home_possession": hp,
         "vision_away_possession": ap, "vision_ball_rate": 0.5}
    m.update(over)
    return m


def test_possession_trend_includes_only_measured_runs():
    matches = [_match("measured"), _match("indicative"), _match("unusable"),
               _match("")]

    trend = season.possession_trend(matches)

    assert len(trend) == 1
    assert trend[0]["home_possession"] == 60.0


def test_possession_trend_can_follow_one_team_across_home_and_away():
    matches = [
        _match("measured", hp=62.0, ap=38.0),
        _match("measured", hp=45.0, ap=55.0, home_team="Hawks",
               away_team="Eagles"),
    ]

    trend = season.possession_trend(matches, team="Eagles")

    assert [r["possession"] for r in trend] == [62.0, 55.0]
    assert [r["home"] for r in trend] == [True, False]


def test_vision_coverage_is_an_honest_denominator():
    matches = [_match("measured"), _match("measured"), _match("indicative"),
               _match("")]

    cov = season.vision_coverage(matches)

    assert cov == {"matches": 4, "measured": 2, "indicative": 1, "unusable": 0,
                   "none": 1, "measured_pct": 50, "mean_ball_rate": 0.5}


def test_vision_coverage_handles_a_season_with_no_camera_runs():
    cov = season.vision_coverage([_match(""), _match("")])

    assert cov["measured"] == 0
    assert cov["measured_pct"] == 0
    assert cov["mean_ball_rate"] == 0.0


# --------------------------------------------------------------------------- #
# First-run readiness (drives the Get started panel)
# --------------------------------------------------------------------------- #
def _base_state(**over):
    import control
    s = {**control.DEFAULT}
    s["teams"] = {"home": {"name": "", "lineup": ""},
                  "away": {"name": "", "lineup": ""}}
    s["feed"] = dict(control.DEFAULT["feed"])
    s.update(over)
    return s


def _vision_deps_ok(monkeypatch):
    """Pretend the vision extras are installed.

    Whether cv2/torch are present is a property of the machine, not of the logic
    under test — and they are deliberately absent on CI.
    """
    import sys
    import types
    stub = types.ModuleType("vision_runner")
    stub.is_supported = lambda: (True, "")
    monkeypatch.setitem(sys.modules, "vision_runner", stub)


def test_setup_state_flags_a_missing_feed_as_blocking(monkeypatch):
    import control
    _vision_deps_ok(monkeypatch)

    setup = control.setup_state(_base_state(ingest_mode="vision"))

    assert setup["ready"] is False
    assert "feed" in {s["key"] for s in setup["outstanding_required"]}


def test_setup_state_is_ready_once_the_feed_is_configured(monkeypatch):
    import control
    _vision_deps_ok(monkeypatch)

    state = _base_state(ingest_mode="vision")
    state["feed"]["url"] = "https://veo.example/live/index.m3u8"
    setup = control.setup_state(state)

    assert setup["ready"] is True
    # Calibration stays outstanding but must not block the match.
    assert all(not s["required"] for s in setup["outstanding"])


def test_voice_only_does_not_demand_a_camera():
    """The blocking steps must follow the ingest mode, not assume vision."""
    import control

    setup = control.setup_state(_base_state(ingest_mode="voice"))

    keys = {s["key"] for s in setup["steps"]}
    assert "feed" not in keys and "deps" not in keys
    assert setup["ready"] is True


def test_naming_teams_is_advisory_not_blocking():
    import control

    state = _base_state(ingest_mode="voice")
    setup = control.setup_state(state)
    teams = next(s for s in setup["steps"] if s["key"] == "teams")

    assert teams["done"] is False
    assert teams["required"] is False

    state["teams"] = {"home": {"name": "Eagles", "lineup": ""},
                      "away": {"name": "Hawks", "lineup": ""}}
    setup = control.setup_state(state)
    assert next(s for s in setup["steps"] if s["key"] == "teams")["done"] is True


def test_every_step_names_the_page_that_fixes_it(monkeypatch):
    """A checklist item that doesn't say where to go is not guidance."""
    import control
    _vision_deps_ok(monkeypatch)

    for state in (_base_state(ingest_mode="vision"),
                  _base_state(ingest_mode="voice"),
                  _base_state(ingest_mode="both")):
        for step in control.setup_state(state)["steps"]:
            assert step["page"]
            assert step["label"]
