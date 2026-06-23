#!/usr/bin/env python3
"""
desktop.py — Kickoff Pulse in a native desktop window.

The browser launcher (kickoff.sh) opens the Streamlit dashboard in a browser
tab. This launcher does the same thing but hosts the dashboard inside a native
macOS window (via pywebview) so the app gets its own window and dock icon.

It owns two child processes:
  * audio_tracker.py — "The Ear + The Brain" (mic -> transcript -> JSON events)
  * streamlit         — "The Display", run headless on a local port

When the window closes (or Cmd-Q), both children are stopped cleanly.

Run directly for testing:  .venv/bin/python desktop.py
Normally launched by the "Kickoff Pulse.app" bundle.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import webview

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
STARTUP_TIMEOUT = float(os.environ.get("KICKOFF_STARTUP_TIMEOUT", "45"))


def _pick_port() -> int:
    """Use KICKOFF_PORT if set, else grab a free port so we never collide
    with a separate kickoff.sh session already holding 8501."""
    forced = os.environ.get("KICKOFF_PORT")
    if forced:
        return int(forced)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


PORT = _pick_port()
URL = f"http://{HOST}:{PORT}"

_children: list[subprocess.Popen] = []


def _spawn(args: list[str], name: str) -> subprocess.Popen:
    """Start a child process in the project root, in its own process group."""
    print(f"[desktop] starting {name}: {' '.join(args)}", flush=True)
    proc = subprocess.Popen(
        args,
        cwd=str(ROOT),
        env=os.environ.copy(),
        start_new_session=True,  # own process group so we can signal the tree
    )
    _children.append(proc)
    return proc


def _server_ready() -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=1) as resp:
            return resp.status < 500
    except Exception:
        return False


def _wait_for_server() -> bool:
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if _server_ready():
            return True
        time.sleep(0.5)
    return False


def _shutdown() -> None:
    """Stop all child processes cleanly, escalating to SIGKILL if needed."""
    print("[desktop] shutting down child processes...", flush=True)
    for proc in _children:
        if proc.poll() is not None:
            continue
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.time() + 5
    for proc in _children:
        remaining = max(0.0, deadline - time.time())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    print("[desktop] all child processes stopped.", flush=True)


def main() -> int:
    os.chdir(ROOT)

    # The Ear + The Brain: live mic -> transcript -> match_data.json
    _spawn([sys.executable, "audio_tracker.py"], "audio tracker")

    # The Display: Streamlit, headless so it does NOT open a browser tab.
    _spawn(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "dashboard.py",
            "--server.headless",
            "true",
            "--server.address",
            HOST,
            "--server.port",
            str(PORT),
            "--browser.gatherUsageStats",
            "false",
            # No hot-reload in a packaged app. The auto file watcher opens an
            # fd per file across .venv + the project, exhausting the process
            # fd limit ("Too many open files"); disabling it is the clean fix.
            "--server.fileWatcherType",
            "none",
        ],
        "streamlit",
    )

    if not _wait_for_server():
        print(
            f"[desktop] Streamlit did not come up at {URL} within "
            f"{STARTUP_TIMEOUT:.0f}s.",
            file=sys.stderr,
            flush=True,
        )
        _shutdown()
        return 1

    print(f"[desktop] dashboard ready at {URL}", flush=True)
    webview.create_window(
        "Kickoff Pulse",
        URL,
        width=1320,
        height=900,
        min_size=(900, 640),
    )
    try:
        # Blocks until every window is closed.
        webview.start()
    finally:
        _shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
