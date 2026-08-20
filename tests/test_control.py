"""Tests for control.py — the match clock, shared state, and match lifecycle.

This module owns the one thing that cannot be re-run: the match clock. It also
owns the only destructive action in the app (starting a new match), so both get
close attention here.
"""

import importlib
import json
import os

import pytest


@pytest.fixture
def ctl(tmp_path, monkeypatch):
    """control + stats pointed at throwaway files, cwd inside them."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KICKOFF_CONTROL_FILE", "control.json")
    monkeypatch.setenv("KICKOFF_NOTES_FILE", "notes.json")
    monkeypatch.setenv("KICKOFF_STATUS_FILE", "status.json")
    monkeypatch.setenv("KICKOFF_DATA_FILE", "match_data.json")
    import control
    import stats
    importlib.reload(control)
    importlib.reload(stats)
    yield control, stats
    monkeypatch.undo()
    importlib.reload(control)
    importlib.reload(stats)


# --------------------------------------------------------------------------- #
# The match clock
# --------------------------------------------------------------------------- #
def test_clock_counts_only_while_running(ctl, monkeypatch):
    control, _ = ctl
    now = [1000.0]
    monkeypatch.setattr(control.time, "time", lambda: now[0])

    state = control.load_control()
    control.timer_start(state)
    now[0] += 65
    assert control.elapsed_seconds(state["timer"]) == pytest.approx(65)

    control.timer_pause(state)
    now[0] += 300                       # time passes while paused
    assert control.elapsed_seconds(state["timer"]) == pytest.approx(65)

    control.timer_start(state)          # resumes from the banked total
    now[0] += 10
    assert control.elapsed_seconds(state["timer"]) == pytest.approx(75)


def test_starting_an_already_running_clock_does_not_lose_time(ctl, monkeypatch):
    """A double-click on Start must not reset the elapsed count."""
    control, _ = ctl
    now = [1000.0]
    monkeypatch.setattr(control.time, "time", lambda: now[0])

    state = control.load_control()
    control.timer_start(state)
    now[0] += 30
    control.timer_start(state)          # second click
    now[0] += 10

    assert control.elapsed_seconds(state["timer"]) == pytest.approx(40)


def test_clock_label_splits_added_time_at_the_half_boundary(ctl):
    control, _ = ctl
    t = {"running": False, "start_epoch": None, "second_half": False}

    assert control.clock_label({**t, "accumulated": 90}) == ("01:30", "", "1st Half")
    # Past 45:00 the main clock pins and the surplus becomes added time.
    main, added, half = control.clock_label({**t, "accumulated": 45 * 60 + 95})
    assert (main, added, half) == ("45:00", "+01:35", "1st Half")


def test_clock_label_uses_the_full_time_boundary_in_the_second_half(ctl):
    control, _ = ctl
    t = {"running": False, "start_epoch": None, "second_half": True,
         "accumulated": 90 * 60 + 30}

    assert control.clock_label(t) == ("90:00", "+00:30", "2nd Half")


def test_halftime_snaps_to_45_and_switches_half(ctl):
    control, _ = ctl
    state = control.load_control()
    control.timer_start(state)

    control.timer_halftime(state)

    assert state["timer"]["accumulated"] == 45 * 60
    assert state["timer"]["second_half"] is True
    assert state["timer"]["running"] is False


def test_timer_reset_clears_the_clock_but_not_the_match(ctl):
    control, _ = ctl
    state = control.load_control()
    state["match_name"] = "Eagles vs Hawks"
    control.timer_start(state)

    control.timer_reset(state)

    assert control.elapsed_seconds(state["timer"]) == 0
    assert state["match_name"] == "Eagles vs Hawks"   # reset != new match


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def test_control_round_trips_and_fills_defaults(ctl):
    control, _ = ctl
    state = control.load_control()
    state["match_name"] = "Eagles vs Hawks"
    state["noise_gate"] = 71
    control.save_control(state)

    reloaded = control.load_control()

    assert reloaded["match_name"] == "Eagles vs Hawks"
    assert reloaded["noise_gate"] == 71
    assert reloaded["ingest_mode"] == "vision"      # default filled in
    assert "feed" in reloaded


def test_a_corrupt_control_file_falls_back_to_defaults(ctl, tmp_path):
    """A half-written file must not take the app down mid-match."""
    control, _ = ctl
    (tmp_path / "control.json").write_text("{not json", encoding="utf-8")

    state = control.load_control()

    assert state["ingest_mode"] == "vision"
    assert state["timer"]["running"] is False


def test_save_is_atomic_leaving_no_temp_files(ctl, tmp_path):
    control, _ = ctl
    control.save_control(control.load_control())

    assert not [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]
    json.loads((tmp_path / "control.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Match identity + lifecycle
# --------------------------------------------------------------------------- #
def test_a_match_id_is_minted_and_stable(ctl):
    control, _ = ctl
    first = control.load_control()["match_id"]

    assert first
    assert control.load_control()["match_id"] == first   # stable across loads


def test_legacy_control_files_gain_a_match_id(ctl, tmp_path):
    control, _ = ctl
    (tmp_path / "control.json").write_text(
        json.dumps({"match_name": "Old Match"}), encoding="utf-8")

    state = control.load_control()

    assert state["match_id"]
    assert state["match_name"] == "Old Match"


def test_unsaved_work_is_detected(ctl):
    control, stats = ctl
    state = control.load_control()
    assert control.has_unsaved_work(state) is False      # nothing logged yet

    stats.save_events([{"team": "Home", "action": "goal", "status": "approved"}])
    assert control.has_unsaved_work(control.load_control()) is True

    control.mark_archived(control.load_control())
    assert control.has_unsaved_work(control.load_control()) is False


def test_new_match_clears_the_working_files(ctl):
    """The regression that made consecutive matches merge into one log."""
    control, stats = ctl
    state = control.load_control()
    old_id = state["match_id"]
    stats.save_events([{"team": "Home", "action": "goal", "status": "approved"}])
    control.add_written_note("a note", state)
    control.timer_start(state)
    control.save_control(state)

    fresh = control.new_match(control.load_control())

    assert fresh["match_id"] != old_id
    assert stats.load_events() == []
    assert control.load_notes() == []
    assert control.elapsed_seconds(fresh["timer"]) == 0
    assert fresh["summary"] == ""
    assert fresh["archived_at"] == ""


def test_new_match_keeps_the_setup_you_would_retype(ctl):
    control, _ = ctl
    state = control.load_control()
    state["teams"] = {"home": {"name": "Eagles", "lineup": "#1 GK"},
                      "away": {"name": "Hawks", "lineup": ""}}
    state["feed"]["url"] = "https://veo.example/live/index.m3u8"
    control.save_control(state)

    fresh = control.new_match(control.load_control(), keep_teams=True,
                              keep_feed=True)

    assert fresh["teams"]["home"]["name"] == "Eagles"
    assert fresh["feed"]["url"] == "https://veo.example/live/index.m3u8"
    assert fresh["match_name"] == ""       # but the fixture itself is cleared


def test_new_match_can_clear_the_setup_too(ctl):
    control, _ = ctl
    state = control.load_control()
    state["teams"]["home"]["name"] = "Eagles"
    state["feed"]["url"] = "https://veo.example/x.m3u8"
    control.save_control(state)

    fresh = control.new_match(control.load_control(), keep_teams=False,
                              keep_feed=False)

    assert fresh["teams"]["home"]["name"] == ""
    assert fresh["feed"]["url"] == ""


def test_notes_are_stamped_with_the_match_they_belong_to(ctl):
    control, _ = ctl
    state = control.load_control()

    note = control.add_written_note("tactical read", state)

    assert note["match_id"] == state["match_id"]


# --------------------------------------------------------------------------- #
# Ingest mode + feed
# --------------------------------------------------------------------------- #
def test_ingest_mode_helpers(ctl):
    control, _ = ctl

    assert control.uses_vision({"ingest_mode": "vision"}) is True
    assert control.uses_voice({"ingest_mode": "vision"}) is False
    assert control.uses_vision({"ingest_mode": "both"}) is True
    assert control.uses_voice({"ingest_mode": "both"}) is True
    assert control.uses_vision({"ingest_mode": "voice"}) is False
    assert control.uses_voice({"ingest_mode": "voice"}) is True


def test_noise_gate_maps_onto_the_threshold_range(ctl):
    control, _ = ctl

    assert control.gate_to_threshold(0) == control.NOISE_GATE_MIN
    assert control.gate_to_threshold(100) == control.NOISE_GATE_MAX
    # Out-of-range and junk values clamp rather than explode mid-match.
    assert control.gate_to_threshold(500) == control.NOISE_GATE_MAX
    assert control.gate_to_threshold("nonsense") == control.gate_to_threshold(
        control.DEFAULT_NOISE_GATE)


# --------------------------------------------------------------------------- #
# Notes
# --------------------------------------------------------------------------- #
def test_notes_append_and_delete(ctl):
    control, _ = ctl
    state = control.load_control()
    a = control.add_written_note("first", state)
    control.add_written_note("second", state)

    assert len(control.load_notes()) == 2
    assert control.delete_note(a["timestamp"]) is True
    assert [n["text"] for n in control.load_notes()] == ["second"]
    assert control.delete_note("no-such-timestamp") is False


def test_tracker_online_uses_status_freshness(ctl, monkeypatch):
    control, _ = ctl
    now = 10_000.0
    monkeypatch.setattr(control.time, "time", lambda: now)

    assert control.tracker_online({"updated": now - 1}) is True
    assert control.tracker_online({"updated": now - 60}) is False
    assert control.tracker_online({}) is False


# --------------------------------------------------------------------------- #
# Match phase (drives the lifecycle chip)
# --------------------------------------------------------------------------- #
def test_match_phase_reads_the_clock_and_archive_flag(ctl):
    control, stats = ctl
    state = control.load_control()

    assert control.match_phase(state, events=[]) == "empty"

    control.timer_start(state)
    assert control.match_phase(state, events=[]) == "live"

    control.timer_pause(state)
    assert control.match_phase(state, events=[{"action": "goal"}]) == "finished"

    control.timer_halftime(state)
    assert control.match_phase(state, events=[{"action": "goal"}]) == "halftime"


def test_archived_beats_every_other_phase(ctl):
    control, _ = ctl
    state = control.load_control()
    control.timer_start(state)
    control.save_control(state)
    control.mark_archived(control.load_control())

    assert control.match_phase(control.load_control()) == "archived"


def test_a_new_match_returns_to_empty(ctl):
    control, stats = ctl
    state = control.load_control()
    stats.save_events([{"action": "goal", "team": "Home"}])
    control.timer_start(state)
    control.save_control(state)
    control.mark_archived(control.load_control())

    fresh = control.new_match(control.load_control())

    assert control.match_phase(fresh) == "empty"


# --------------------------------------------------------------------------- #
# Readable durations
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("seconds,expected", [
    (0, "0 s"),
    (30, "30 s"),
    (59.4, "59 s"),
    (59.6, "1 min"),      # must not read "60 s"
    (60, "1 min"),
    (90, "2 min"),
    (2700, "45 min"),
    (3600, "1 h 00 min"),
    (5400, "1 h 30 min"),
])
def test_human_duration_reads_naturally(ctl, seconds, expected):
    control, _ = ctl
    assert control.human_duration(seconds) == expected


def test_human_duration_never_returns_a_negative_length(ctl):
    control, _ = ctl
    assert control.human_duration(-5) == "0 s"
