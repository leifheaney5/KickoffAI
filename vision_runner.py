#!/usr/bin/env python3
"""
Kickoff Pulse — vision runner supervisor (the Eye's remote control).

The vision pipeline runs as its own persistent process (scripts/live_vision.py)
so it keeps analysing the match no matter what you click in the app. This module
is how the UI starts, pauses and stops that process without ever holding a
subprocess handle across a Streamlit rerun: state lives in a small JSON file and
liveness is checked by PID, mirroring screen_recorder.py.

Public API, deliberately shaped like screen_recorder's:

    is_supported()  -> bool          vision deps + model weights available
    status()        -> dict          running / pid / elapsed / health / stats
    start(state)    -> dict          spawn the runner from control.feed
    stop()          -> dict          SIGTERM, wait for the final checkpoint
    pause()/resume()-> dict          idle the runner at half-time
    log_tail()      -> str           the runner's recent stdout
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time

import control

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

RECORD_DIR = os.environ.get("KICKOFF_RECORD_DIR", "recordings")
STATE_FILE = os.environ.get("KICKOFF_VISION_STATE_FILE", "vision_runner.json")
LOG_FILE = os.path.join(RECORD_DIR, "live_vision.log")

# Written by the runner itself; see scripts/live_vision.py. The PID file is
# removed only after the final checkpoint, so it doubles as a "stats are saved"
# signal for stop().
RUNNER_STATUS_FILE = "live_eye_status.json"
RUNNER_PID_FILE = ".live_vision.pid"
SNAPSHOT_FILE = os.path.join(RECORD_DIR, "live_eye.jpg")
PAUSE_FLAG = ".live_eye_paused"

# A run is "stale" when the runner has not checkpointed in this long. The runner
# checkpoints every 10s by default, so this leaves room for a slow model step.
STALE_AFTER = 30.0

# Grace period after spawn before we judge a run stale — opening a stream and
# loading model weights can take a while on first use.
STARTUP_GRACE = 90.0


# --------------------------------------------------------------------------- #
# State file (atomic, mirrors control.py / screen_recorder.py)
# --------------------------------------------------------------------------- #
def _write_state(data: dict) -> None:
    directory = os.path.dirname(os.path.abspath(STATE_FILE)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        control.atomic_replace(tmp, STATE_FILE)
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


def _read_runner_status() -> dict:
    """The runner's own health file (frames, fps, possession, last checkpoint)."""
    if not os.path.exists(RUNNER_STATUS_FILE):
        return {}
    try:
        with open(RUNNER_STATUS_FILE, "r", encoding="utf-8") as fh:
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
# Capability
# --------------------------------------------------------------------------- #
def is_supported() -> tuple[bool, str]:
    """(ok, reason). Vision deps importable and the runner script present."""
    if not os.path.exists(os.path.join(REPO_ROOT, "scripts", "live_vision.py")):
        return False, "scripts/live_vision.py is missing."
    try:
        import cv2  # noqa: F401
        from vision import MatchAnalyzer  # noqa: F401
    except Exception as exc:
        return False, (f"Vision dependencies are not installed ({exc}). "
                       "Run: pip install -r vision/requirements.txt")
    return True, ""


def model_available(state: dict) -> bool:
    """True when the configured weights file exists on disk."""
    model = (state.get("feed") or {}).get("model") or ""
    if not model:
        return False
    # Ultralytics resolves bare names like "yolov8m.pt" by downloading them, so
    # only treat an explicit path that doesn't exist as missing.
    return os.path.exists(os.path.join(REPO_ROOT, model)) or "/" not in model


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
def status() -> dict:
    """Current runner state. Self-heals if the process died on its own."""
    st = _read_state()
    running = bool(st.get("running"))
    if running and not _pid_alive(st.get("pid")):
        st = {**st, "running": False, "pid": None, "ended_unexpectedly": True}
        _write_state(st)
        running = False

    started_at = st.get("started_at")
    elapsed = (time.time() - started_at) if (running and started_at) else 0.0
    runner = _read_runner_status() if running else {}
    paused = os.path.exists(PAUSE_FLAG)

    return {
        "running": running,
        "paused": running and paused,
        "pid": st.get("pid"),
        "elapsed": elapsed,
        "started_at": started_at,
        "source": st.get("source"),
        "source_label": st.get("source_label", ""),
        "log": st.get("log", LOG_FILE),
        "ended_unexpectedly": st.get("ended_unexpectedly", False),
        "health": _health(running, paused, started_at, runner),
        # Live figures from the runner's own checkpoint (empty until the first).
        "frames": runner.get("frames", 0),
        "fps": runner.get("fps", 0.0),
        "passes": runner.get("passes", 0),
        "possession_home": runner.get("possession_home", 0.0),
        "possession_away": runner.get("possession_away", 0.0),
        "ball_rate": runner.get("ball_rate", 0.0),
        "match_time": runner.get("match_time", ""),
        "last_frame_at": runner.get("updated"),
        "reconnects": runner.get("reconnects", 0),
    }


def _health(running: bool, paused: bool, started_at, runner: dict) -> str:
    """One of: down | starting | paused | ok | stale."""
    if not running:
        return "down"
    if paused:
        return "paused"
    updated = runner.get("updated")
    if not updated:
        # No checkpoint yet — fine during startup, a problem after that.
        age = time.time() - (started_at or 0)
        return "starting" if age < STARTUP_GRACE else "stale"
    return "ok" if (time.time() - updated) < STALE_AFTER else "stale"


def health_label(st: dict) -> str:
    """Human-readable health for the status chips."""
    return {
        "ok": "running",
        "starting": "starting",
        "paused": "paused",
        "stale": "not responding",
        "down": "stopped",
    }.get(st.get("health", "down"), "stopped")


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
def build_argv(state: dict) -> list[str]:
    """The command line for scripts/live_vision.py from the saved feed config.

    Kept separate from :func:`start` so it can be unit-tested (and shown to the
    user) without spawning anything.
    """
    feed = state.get("feed") or control.DEFAULT["feed"]
    source = control.feed_source(state)
    from vision.runtime import resolve_device

    argv = [
        sys.executable,
        os.path.join(REPO_ROOT, "scripts", "live_vision.py"),
        "--model", str(feed.get("model") or "soccer_yolov8m_v1.pt"),
        "--device", resolve_device(feed.get("device", "auto")),
        "--stride", str(int(feed.get("stride", 6) or 6)),
        "--imgsz", str(int(feed.get("imgsz", 960) or 960)),
        "--conf", str(float(feed.get("conf", 0.25) or 0.25)),
    ]
    if feed.get("kind") == "webcam":
        argv += ["--camera", str(int(source or 0))]
    else:
        argv += ["--video", str(source)]
    return argv


def start(state: dict = None) -> dict:
    """Start the Eye from the saved feed config. Returns a result dict."""
    state = control.load_control() if state is None else state

    ok, reason = is_supported()
    if not ok:
        return {"ok": False, "error": reason}
    if status()["running"]:
        return {"ok": False, "error": "The Eye is already running."}
    if not control.feed_ready(state):
        return {"ok": False,
                "error": "No feed is configured. Set one up on Camera & Feed."}

    # A stale pause flag from a previous match would idle the new run instantly.
    _clear_pause_flag()

    argv = build_argv(state)
    os.makedirs(RECORD_DIR, exist_ok=True)
    log_fh = open(LOG_FILE, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(argv, cwd=REPO_ROOT, stdin=subprocess.DEVNULL,
                                stdout=log_fh, stderr=subprocess.STDOUT,
                                start_new_session=True)
    except OSError as exc:
        return {"ok": False, "error": f"Could not start the vision runner: {exc}"}
    finally:
        log_fh.close()

    # A bad URL or missing weights fails fast; surface that instead of showing a
    # "running" chip for a process that has already exited.
    time.sleep(1.5)
    if proc.poll() is not None:
        return {"ok": False,
                "error": "The vision runner exited immediately.",
                "detail": log_tail()}

    _write_state({
        "running": True,
        "pid": proc.pid,
        "started_at": time.time(),
        "source": str(control.feed_source(state)),
        "source_label": control.feed_label(state),
        "log": LOG_FILE,
        "argv": argv,
        "ended_unexpectedly": False,
    })
    return {"ok": True, "pid": proc.pid, "source": control.feed_label(state)}


def stop(timeout: float = 25.0) -> dict:
    """Stop the Eye, waiting for its final checkpoint to land.

    The runner traps SIGTERM and, on the way out, saves a final checkpoint and
    only then removes its PID file. So the PID file vanishing — not the process
    exiting — is the signal that the accumulated possession/passing is safely on
    disk. Waiting on process exit instead would block the UI for ~20s while
    torch tears down its MPS/CUDA context, long after the data was saved.
    """
    st = _read_state()
    pid = st.get("pid")
    if not st.get("running") or not _pid_alive(pid):
        _write_state({**st, "running": False, "pid": None})
        _clear_pause_flag()
        return {"ok": False, "error": "The Eye is not running."}

    try:
        os.kill(int(pid), signal.SIGTERM)
    except (OSError, ValueError) as exc:
        _write_state({**st, "running": False, "pid": None})
        return {"ok": False, "error": f"Could not signal the runner: {exc}"}

    deadline = time.time() + timeout
    saved = False
    while time.time() < deadline:
        if not os.path.exists(RUNNER_PID_FILE):
            saved = True          # final checkpoint written
            break
        if not _pid_alive(pid):
            saved = True          # exited outright; its finally block ran
            break
        time.sleep(0.1)

    # The data is safe once the PID file is gone, so don't make the user wait on
    # a slow interpreter teardown — reap the process and return.
    if _pid_alive(pid):
        try:
            os.kill(int(pid), signal.SIGKILL)
        except OSError:
            pass

    _write_state({**st, "running": False, "pid": None})
    _clear_pause_flag()
    if not saved:
        return {"ok": True, "checkpoint_saved": False,
                "error": "Stopped, but the runner did not confirm a final "
                         "checkpoint in time; stats may be up to one "
                         "checkpoint interval old."}
    return {"ok": True, "checkpoint_saved": True}


def _clear_pause_flag() -> None:
    try:
        os.remove(PAUSE_FLAG)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def pause() -> dict:
    """Idle the runner (half-time) without losing accumulated stats."""
    if not status()["running"]:
        return {"ok": False, "error": "The Eye is not running."}
    open(PAUSE_FLAG, "w", encoding="utf-8").close()
    return {"ok": True}


def resume() -> dict:
    """Resume from the live edge after a pause."""
    _clear_pause_flag()
    return {"ok": True}


def log_tail(n: int = 2000) -> str:
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()[-n:].strip()
    except OSError:
        return ""


def snapshot_age() -> float | None:
    """Seconds since the annotated frame was last written, or None."""
    try:
        return time.time() - os.path.getmtime(SNAPSHOT_FILE)
    except OSError:
        return None


def reconcile() -> dict:
    """Drop state that points at a dead process. Used by the app-doctor skill."""
    st = _read_state()
    if st.get("running") and not _pid_alive(st.get("pid")):
        _write_state({**st, "running": False, "pid": None,
                      "ended_unexpectedly": True})
        return {"cleaned": True, "pid": st.get("pid")}
    return {"cleaned": False}
