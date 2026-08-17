"""Tests for the vision runner supervisor and the feed config it reads."""

import importlib
import json
import os
import time

import pytest

import control
import vision_runner


@pytest.fixture
def runner_env(tmp_path, monkeypatch):
    """Point control + vision_runner at throwaway files for one test."""
    monkeypatch.setenv("KICKOFF_CONTROL_FILE", str(tmp_path / "control.json"))
    monkeypatch.setenv("KICKOFF_VISION_STATE_FILE", str(tmp_path / "runner.json"))
    monkeypatch.chdir(tmp_path)

    importlib.reload(control)
    importlib.reload(vision_runner)
    yield control, vision_runner
    # Restore the modules for any test that imports them without the fixture.
    monkeypatch.undo()
    importlib.reload(control)
    importlib.reload(vision_runner)


# --------------------------------------------------------------------------- #
# Feed config
# --------------------------------------------------------------------------- #
def test_feed_defaults_are_vision_first(runner_env):
    ctl, _ = runner_env
    state = ctl.load_control()

    assert state["ingest_mode"] == "vision"
    assert ctl.uses_vision(state) is True
    assert ctl.uses_voice(state) is False
    # Nothing configured yet, so the Eye must not claim to be ready.
    assert ctl.feed_ready(state) is False
    assert ctl.feed_source(state) is None


def test_old_control_files_gain_feed_defaults(runner_env, tmp_path):
    """A control.json written before this feature still loads cleanly."""
    ctl, _ = runner_env
    (tmp_path / "control.json").write_text(
        json.dumps({"match_name": "Eagles vs Hawks", "noise_gate": 55}),
        encoding="utf-8")

    state = ctl.load_control()

    assert state["match_name"] == "Eagles vs Hawks"
    assert state["noise_gate"] == 55           # existing keys survive
    assert state["feed"]["kind"] == "stream"   # new keys are filled in
    assert state["ingest_mode"] == "vision"


def test_invalid_ingest_mode_falls_back_to_vision(runner_env, tmp_path):
    ctl, _ = runner_env
    (tmp_path / "control.json").write_text(
        json.dumps({"ingest_mode": "telepathy"}), encoding="utf-8")

    assert ctl.load_control()["ingest_mode"] == "vision"


@pytest.mark.parametrize("kind,field,value,expected", [
    ("stream", "url", "https://veo.example/live/index.m3u8",
     "https://veo.example/live/index.m3u8"),
    ("file", "file_path", "recordings/match.mp4", "recordings/match.mp4"),
    ("webcam", "camera_index", 2, 2),
])
def test_feed_source_per_kind(runner_env, kind, field, value, expected):
    ctl, _ = runner_env
    state = ctl.load_control()
    state["feed"]["kind"] = kind
    state["feed"][field] = value

    assert ctl.feed_source(state) == expected
    assert ctl.feed_ready(state) is True


def test_blank_stream_url_is_not_ready(runner_env):
    ctl, _ = runner_env
    state = ctl.load_control()
    state["feed"]["url"] = "   "

    assert ctl.feed_source(state) is None
    assert ctl.feed_ready(state) is False


# --------------------------------------------------------------------------- #
# Written match notes
# --------------------------------------------------------------------------- #
def test_written_note_is_stamped_and_tagged(runner_env, tmp_path, monkeypatch):
    ctl, _ = runner_env
    monkeypatch.setenv("KICKOFF_NOTES_FILE", str(tmp_path / "notes.json"))
    importlib.reload(ctl)

    state = ctl.load_control()
    state["timer"] = {"running": False, "start_epoch": None,
                      "accumulated": 12 * 60 + 30, "second_half": False}

    note = ctl.add_written_note("  Back four sitting too deep  ", state)

    assert note["text"] == "Back four sitting too deep"     # trimmed
    assert note["match_time"] == "12:30"                    # match clock, not wall
    assert note["source"] == "written"
    assert note["audio"] is None
    assert ctl.load_notes() == [note]


def test_written_note_rejects_empty_text(runner_env, tmp_path, monkeypatch):
    ctl, _ = runner_env
    monkeypatch.setenv("KICKOFF_NOTES_FILE", str(tmp_path / "notes.json"))
    importlib.reload(ctl)

    with pytest.raises(ValueError):
        ctl.add_written_note("   ", ctl.load_control())
    assert ctl.load_notes() == []


def test_note_source_defaults_to_voice_for_legacy_notes(runner_env):
    """Notes written before the field existed all came from the mic."""
    ctl, _ = runner_env

    assert ctl.note_source({"text": "old note"}) == "voice"
    assert ctl.note_source({"text": "x", "source": "written"}) == "written"
    assert ctl.note_source({"text": "x", "source": "voice"}) == "voice"
    assert ctl.note_source({"text": "x", "source": "nonsense"}) == "voice"


def test_written_and_spoken_notes_share_one_log(runner_env, tmp_path, monkeypatch):
    """Both kinds land in notes.json, so the report and library pick up both."""
    ctl, _ = runner_env
    monkeypatch.setenv("KICKOFF_NOTES_FILE", str(tmp_path / "notes.json"))
    importlib.reload(ctl)

    ctl.append_note({"timestamp": "2026-08-17T10:00:00+00:00",
                     "match_time": "05:00", "text": "spoken",
                     "audio": "notes_audio/a.wav", "source": "voice"})
    ctl.add_written_note("typed", ctl.load_control())

    notes = ctl.load_notes()
    assert [ctl.note_source(n) for n in notes] == ["voice", "written"]
    assert ctl.delete_note(notes[0]["timestamp"]) is True
    assert len(ctl.load_notes()) == 1


# --------------------------------------------------------------------------- #
# Command line construction
# --------------------------------------------------------------------------- #
def test_argv_passes_stream_url_as_video(runner_env):
    ctl, vr = runner_env
    state = ctl.load_control()
    state["feed"].update({"kind": "stream", "device": "cpu", "stride": 4,
                          "url": "https://veo.example/live/index.m3u8"})

    argv = vr.build_argv(state)

    assert argv[1].endswith("scripts/live_vision.py")
    assert "--video" in argv
    assert argv[argv.index("--video") + 1] == "https://veo.example/live/index.m3u8"
    assert argv[argv.index("--device") + 1] == "cpu"
    assert argv[argv.index("--stride") + 1] == "4"
    assert "--camera" not in argv


def test_argv_uses_camera_flag_for_webcam(runner_env):
    """A digit passed to --video would resolve as a file path, not a device."""
    ctl, vr = runner_env
    state = ctl.load_control()
    state["feed"].update({"kind": "webcam", "camera_index": 0})

    argv = vr.build_argv(state)

    assert "--video" not in argv
    assert argv[argv.index("--camera") + 1] == "0"


def test_argv_resolves_auto_device(runner_env, monkeypatch):
    ctl, vr = runner_env
    import vision.runtime as vrt
    monkeypatch.setattr(vrt, "best_device", lambda: "mps")

    state = ctl.load_control()
    state["feed"].update({"url": "https://veo.example/x.m3u8", "device": "auto"})

    argv = vr.build_argv(state)

    assert argv[argv.index("--device") + 1] == "mps"


# --------------------------------------------------------------------------- #
# Lifecycle guards
# --------------------------------------------------------------------------- #
def test_start_refuses_without_a_feed(runner_env):
    ctl, vr = runner_env
    res = vr.start(ctl.load_control())

    assert res["ok"] is False
    assert "feed" in res["error"].lower()


def test_status_self_heals_a_dead_pid(runner_env):
    """A crashed runner must not leave the UI showing a running Eye."""
    _, vr = runner_env
    # PID 999999 is not a live process on any normal system.
    vr._write_state({"running": True, "pid": 999999, "started_at": time.time()})

    st = vr.status()

    assert st["running"] is False
    assert st["ended_unexpectedly"] is True
    assert st["health"] == "down"


def test_reconcile_clears_orphan_state(runner_env):
    _, vr = runner_env
    vr._write_state({"running": True, "pid": 999999, "started_at": time.time()})

    assert vr.reconcile()["cleaned"] is True
    assert vr.reconcile()["cleaned"] is False   # idempotent


def test_stop_reports_when_nothing_is_running(runner_env):
    _, vr = runner_env
    res = vr.stop()

    assert res["ok"] is False
    assert "not running" in res["error"].lower()


def test_stop_returns_as_soon_as_the_checkpoint_lands(runner_env, tmp_path,
                                                      monkeypatch):
    """Stop waits on the PID file, not on process exit.

    The runner removes its PID file straight after the final checkpoint, but
    then spends up to ~20s tearing down torch's MPS/CUDA context. Blocking the
    UI for that teardown would make "Stop Eye" feel broken.
    """
    _, vr = runner_env
    # A process that stays alive (this test's own), standing in for the slow
    # teardown, with no PID file — i.e. the checkpoint has already landed.
    vr._write_state({"running": True, "pid": os.getpid(),
                     "started_at": time.time()})
    monkeypatch.setattr(vr.os, "kill", lambda *a: None)   # don't signal ourselves

    started = time.time()
    res = vr.stop(timeout=10.0)

    assert res["ok"] is True
    assert res["checkpoint_saved"] is True
    assert time.time() - started < 1.0


def test_stop_flags_an_unconfirmed_checkpoint(runner_env, tmp_path, monkeypatch):
    """A runner that never drops its PID file is reported honestly."""
    _, vr = runner_env
    (tmp_path / vr.RUNNER_PID_FILE).write_text(str(os.getpid()), encoding="utf-8")
    vr._write_state({"running": True, "pid": os.getpid(),
                     "started_at": time.time()})
    monkeypatch.setattr(vr.os, "kill", lambda *a: None)

    res = vr.stop(timeout=0.3)

    assert res["ok"] is True
    assert res["checkpoint_saved"] is False
    assert "checkpoint" in res["error"].lower()


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
def test_health_is_starting_before_the_first_checkpoint(runner_env):
    _, vr = runner_env
    now = time.time()

    assert vr._health(True, False, now, {}) == "starting"
    # ...but a run that never checkpoints is stale, not perpetually starting.
    assert vr._health(True, False, now - vr.STARTUP_GRACE - 1, {}) == "stale"


def test_health_tracks_checkpoint_freshness(runner_env):
    _, vr = runner_env
    now = time.time()

    assert vr._health(True, False, now, {"updated": now}) == "ok"
    assert vr._health(True, False, now,
                      {"updated": now - vr.STALE_AFTER - 1}) == "stale"
    assert vr._health(True, True, now, {"updated": now}) == "paused"
    assert vr._health(False, False, None, {}) == "down"


def test_status_surfaces_runner_figures(runner_env, tmp_path):
    """The chips read the runner's small health file, not match_stats.json."""
    _, vr = runner_env
    vr._write_state({"running": True, "pid": os.getpid(),
                     "started_at": time.time()})
    (tmp_path / vr.RUNNER_STATUS_FILE).write_text(json.dumps({
        "updated": time.time(), "frames": 1200, "fps": 4.5, "passes": 37,
        "possession_home": 58.0, "possession_away": 42.0, "ball_rate": 0.62,
        "match_time": "34:20",
    }), encoding="utf-8")

    st = vr.status()

    assert st["running"] is True
    assert st["health"] == "ok"
    assert st["frames"] == 1200
    assert st["passes"] == 37
    assert st["possession_home"] == 58.0
    assert vr.health_label(st) == "running"
