#!/usr/bin/env python3
"""
Kickoff Pulse — screen recorder (the Camera).

Captures the screen plus your narration mic to a single video file using the
system ffmpeg + macOS avfoundation. Driven by a one-button toggle on the
dashboard: start spawns ffmpeg, stop sends it SIGINT so the file is finalized
cleanly. State lives in a tiny JSON file (recorder.json) so it survives
Streamlit's reruns — the UI only ever holds the recorder's PID, never the
subprocess handle.

macOS only for now (avfoundation). The process that spawns ffmpeg needs Screen
Recording permission (System Settings → Privacy & Security → Screen Recording);
the first run triggers the system prompt.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time

# Where finished recordings and the live-state file live.
RECORD_DIR = os.environ.get("KICKOFF_RECORD_DIR", "recordings")
STATE_FILE = os.environ.get("KICKOFF_RECORDER_FILE", "recorder.json")

# Reuse the same mic selector the audio tracker uses (e.g. "AirPods").
MIC_SELECT = os.environ.get("KICKOFF_MIC")


def is_supported() -> bool:
    """True on macOS with ffmpeg available."""
    return sys.platform == "darwin" and _ffmpeg_path() is not None


def _ffmpeg_path():
    from shutil import which
    return which("ffmpeg")


# --------------------------------------------------------------------------- #
# Device discovery (avfoundation indices, resolved by name at runtime)
# --------------------------------------------------------------------------- #
def list_devices() -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Return (video_devices, audio_devices) as lists of (index, name)."""
    ff = _ffmpeg_path()
    if not ff:
        return [], []
    proc = subprocess.run(
        [ff, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True, text=True)
    text = proc.stderr
    video, audio, section = [], [], None
    for line in text.splitlines():
        if "AVFoundation video devices" in line:
            section = video
            continue
        if "AVFoundation audio devices" in line:
            section = audio
            continue
        m = re.search(r"\[(\d+)\]\s+(.*)$", line)
        if m and section is not None:
            section.append((int(m.group(1)), m.group(2).strip()))
    return video, audio


def _screen_index(video_devices) -> int | None:
    for idx, name in video_devices:
        if "capture screen" in name.lower():
            return idx
    return None


def _mic_index(audio_devices):
    """Pick the mic: KICKOFF_MIC (index or name substring), else the first."""
    if not audio_devices:
        return None
    if MIC_SELECT:
        if MIC_SELECT.isdigit():
            i = int(MIC_SELECT)
            if any(idx == i for idx, _ in audio_devices):
                return i
        match = next((idx for idx, name in audio_devices
                      if MIC_SELECT.lower() in name.lower()), None)
        if match is not None:
            return match
    return audio_devices[0][0]


# --------------------------------------------------------------------------- #
# State file (atomic, mirrors control.py's pattern)
# --------------------------------------------------------------------------- #
def _write_state(data: dict) -> None:
    directory = os.path.dirname(os.path.abspath(STATE_FILE)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _read_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def status() -> dict:
    """Current recorder state. Self-heals if the ffmpeg process has died."""
    st = _read_state()
    recording = bool(st.get("recording"))
    if recording and not _pid_alive(st.get("pid")):
        # ffmpeg exited on its own (finished, crashed, or permission denied).
        st = {**st, "recording": False, "pid": None, "ended_unexpectedly": True}
        _write_state(st)
        recording = False
    elapsed = (time.time() - st["started_at"]) if (recording and st.get("started_at")) else 0.0
    return {
        "recording": recording,
        "elapsed": elapsed,
        "file": st.get("file"),
        "started_at": st.get("started_at"),
        "log": st.get("log"),
        "ended_unexpectedly": st.get("ended_unexpectedly", False),
    }


def start(label: str = "") -> dict:
    """Start a screen+mic recording. Returns a result dict.

    On failure (no ffmpeg, no screen device, permission denied) returns
    {"ok": False, "error": "..."} and leaves no recording running.
    """
    if not is_supported():
        return {"ok": False, "error": "Screen recording needs macOS + ffmpeg."}
    if status()["recording"]:
        return {"ok": False, "error": "A recording is already in progress."}

    video, audio = list_devices()
    vidx = _screen_index(video)
    if vidx is None:
        return {"ok": False,
                "error": "No 'Capture screen' device found. Grant Screen "
                         "Recording permission, then restart the app."}
    aidx = _mic_index(audio)
    spec = f"{vidx}:{aidx}" if aidx is not None else f"{vidx}:none"

    os.makedirs(RECORD_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-").lower()
    base = f"{stamp}{('-' + slug) if slug else ''}"
    outfile = os.path.join(RECORD_DIR, base + ".mp4")
    logfile = os.path.join(RECORD_DIR, base + ".log")

    # Note: don't force -framerate on avfoundation screen capture — it makes the
    # device configuration fall back and can stall startup. Let it self-select.
    cmd = [
        _ffmpeg_path(), "-y",
        "-f", "avfoundation",
        "-capture_cursor", "1",
        "-i", spec,
        "-c:v", "h264_videotoolbox", "-b:v", "6000k", "-pix_fmt", "yuv420p",
    ]
    if aidx is not None:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    cmd += [outfile]

    log_fh = open(logfile, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=log_fh, stderr=log_fh)
    except OSError as exc:
        return {"ok": False, "error": f"Could not start ffmpeg: {exc}"}
    finally:
        log_fh.close()

    # Give ffmpeg a moment to open the devices; if it dies immediately the most
    # likely cause is a denied Screen Recording permission.
    time.sleep(1.3)
    if proc.poll() is not None:
        err = _log_tail(logfile)
        hint = ("Screen Recording permission is likely denied. Enable it for "
                "your terminal/Python in System Settings → Privacy & Security "
                "→ Screen Recording, then restart the app.")
        return {"ok": False, "error": hint, "detail": err}

    _write_state({
        "recording": True,
        "pid": proc.pid,
        "file": outfile,
        "log": logfile,
        "started_at": time.time(),
        "device": spec,
        "ended_unexpectedly": False,
    })
    return {"ok": True, "file": outfile, "pid": proc.pid}


def stop(timeout: float = 8.0) -> dict:
    """Stop the active recording, finalizing the file via SIGINT."""
    st = _read_state()
    pid = st.get("pid")
    outfile = st.get("file")
    if not st.get("recording") or not _pid_alive(pid):
        _write_state({**st, "recording": False, "pid": None})
        return {"ok": False, "error": "No active recording.", "file": outfile}

    try:
        os.kill(int(pid), signal.SIGINT)
    except (OSError, ValueError) as exc:
        _write_state({**st, "recording": False, "pid": None})
        return {"ok": False, "error": f"Could not signal ffmpeg: {exc}",
                "file": outfile}

    deadline = time.time() + timeout
    while _pid_alive(pid) and time.time() < deadline:
        time.sleep(0.1)
    if _pid_alive(pid):
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass

    _write_state({**st, "recording": False, "pid": None})
    return {"ok": True, "file": outfile}


def _log_tail(path: str, n: int = 1200) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()[-n:].strip()
    except OSError:
        return ""


def list_recordings() -> list[dict]:
    """Finished recordings, newest first."""
    if not os.path.isdir(RECORD_DIR):
        return []
    out = []
    for name in os.listdir(RECORD_DIR):
        if not name.lower().endswith((".mp4", ".mov")):
            continue
        path = os.path.join(RECORD_DIR, name)
        try:
            stt = os.stat(path)
        except OSError:
            continue
        out.append({"name": name, "path": path,
                    "size": stt.st_size, "mtime": stt.st_mtime})
    out.sort(key=lambda r: r["mtime"], reverse=True)
    return out
