"""Tests for the local screen recorder wrapper."""

import importlib
import json
import os

import pytest

import screen_recorder


DEVICE_LISTING = """
[AVFoundation indev @ 0x123] AVFoundation video devices:
[AVFoundation indev @ 0x123] [0] MacBook Air Camera
[AVFoundation indev @ 0x123] [1] Capture screen 0
[AVFoundation indev @ 0x123] AVFoundation audio devices:
[AVFoundation indev @ 0x123] [0] MacBook Air Microphone
[AVFoundation indev @ 0x123] [1] AirPods Pro
"""


def test_device_parser_finds_video_and_audio(monkeypatch):
    class Result:
        stderr = DEVICE_LISTING

    monkeypatch.setattr(screen_recorder, "_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(screen_recorder.subprocess, "run", lambda *a, **kw: Result())

    video, audio = screen_recorder.list_devices()

    assert video == [(0, "MacBook Air Camera"), (1, "Capture screen 0")]
    assert audio == [(0, "MacBook Air Microphone"), (1, "AirPods Pro")]
    assert screen_recorder._screen_index(video) == 1


def test_mic_selection_uses_env_name(monkeypatch):
    monkeypatch.setattr(screen_recorder, "MIC_SELECT", "airpods")

    idx = screen_recorder._mic_index([
        (0, "MacBook Air Microphone"),
        (1, "AirPods Pro"),
    ])

    assert idx == 1


def test_status_marks_dead_recording_as_ended(tmp_path, monkeypatch):
    state_file = tmp_path / "recorder.json"
    state_file.write_text(json.dumps({
        "recording": True,
        "pid": 999999,
        "file": "recordings/demo.mp4",
        "started_at": 10.0,
    }))
    monkeypatch.setattr(screen_recorder, "STATE_FILE", str(state_file))
    monkeypatch.setattr(screen_recorder, "_pid_alive", lambda pid: False)

    status = screen_recorder.status()

    assert status["recording"] is False
    assert status["ended_unexpectedly"] is True
    saved = json.loads(state_file.read_text())
    assert saved["recording"] is False
    assert saved["pid"] is None


def test_start_builds_screen_plus_mic_command(tmp_path, monkeypatch):
    importlib.reload(screen_recorder)
    monkeypatch.setattr(screen_recorder.sys, "platform", "darwin")
    monkeypatch.setattr(screen_recorder, "_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(screen_recorder, "STATE_FILE", str(tmp_path / "recorder.json"))
    monkeypatch.setattr(screen_recorder, "RECORD_DIR", str(tmp_path / "recordings"))
    monkeypatch.setattr(screen_recorder, "list_devices", lambda: (
        [(2, "Capture screen 0")],
        [(0, "MacBook Air Microphone")],
    ))
    monkeypatch.setattr(screen_recorder.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(screen_recorder.time, "time", lambda: 100.0)
    monkeypatch.setattr(screen_recorder.time, "strftime", lambda fmt: "20260622-210000")

    launched = {}

    class Proc:
        pid = 12345

        def poll(self):
            return None

    def fake_popen(cmd, stdin, stdout, stderr):
        launched["cmd"] = cmd
        assert stdout is stderr
        assert not stdout.closed
        return Proc()

    monkeypatch.setattr(screen_recorder.subprocess, "Popen", fake_popen)

    result = screen_recorder.start(label="Cup Final")

    assert result == {
        "ok": True,
        "file": os.path.join(str(tmp_path / "recordings"),
                             "20260622-210000-cup-final.mp4"),
        "pid": 12345,
    }
    assert "-i" in launched["cmd"]
    assert launched["cmd"][launched["cmd"].index("-i") + 1] == "2:0"
    assert "-c:a" in launched["cmd"]

    saved = json.loads((tmp_path / "recorder.json").read_text())
    assert saved["recording"] is True
    assert saved["device"] == "2:0"


def test_start_returns_permission_hint_when_ffmpeg_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(screen_recorder.sys, "platform", "darwin")
    monkeypatch.setattr(screen_recorder, "_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(screen_recorder, "STATE_FILE", str(tmp_path / "recorder.json"))
    monkeypatch.setattr(screen_recorder, "RECORD_DIR", str(tmp_path / "recordings"))
    monkeypatch.setattr(screen_recorder, "list_devices", lambda: (
        [(2, "Capture screen 0")],
        [(0, "MacBook Air Microphone")],
    ))
    monkeypatch.setattr(screen_recorder.time, "sleep", lambda seconds: None)

    class Proc:
        pid = 12345

        def poll(self):
            return 1

    def fake_popen(cmd, stdin, stdout, stderr):
        stdout.write("AVFoundation error")
        stdout.flush()
        return Proc()

    monkeypatch.setattr(screen_recorder.subprocess, "Popen", fake_popen)

    result = screen_recorder.start(label="Demo")

    assert result["ok"] is False
    assert "Screen Recording permission" in result["error"]
    assert "AVFoundation error" in result["detail"]
