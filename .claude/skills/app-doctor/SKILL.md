---
name: app-doctor
description: Diagnose and clean up Kickoff Pulse when it is sluggish, frozen, greyed out, or the machine is overloaded — find runaway/orphan processes (ffmpeg recordings, live_vision, stuck captures), reconcile recorder.json, and free resources. Use when the app is "struggling", slow, or unresponsive.
---

# App doctor

Triage when Kickoff Pulse is slow/frozen or the Mac is overloaded.

## 1. Load + heavy processes

```bash
uptime                      # load avg vs cores
sysctl -n hw.ncpu
ps aux | grep -Ei "streamlit|python|ffmpeg|live_vision|audio_tracker" | grep -v grep
```

Load averages well above the core count mean oversubscription — usually too many
concurrent jobs (CV inference + screen recordings + HLS capture + audio).

## 2. Orphan recordings (the usual culprit)

`recorder.json` tracks the *current* recording (`pid`, `file`). Compare it to the
running `ffmpeg -f avfoundation` processes:

- An `ffmpeg` PID **not** in `recorder.json`, or one whose start time is old, is
  an **orphan** from a prior session (starting a new recording can overwrite
  `recorder.json` without stopping the previous capture).
- Confirm a file is still growing: `stat -f%z FILE` twice, a couple seconds apart.
- A `recorder.json` pointing at a dead PID or a file that does not exist is stale.

Stop an orphan **gracefully** so the MP4 finalizes cleanly:

```bash
kill -INT <pid>     # ffmpeg finalizes the moov atom; escalate to -TERM if needed
```

A capture wedged in uninterruptible device I/O (e.g. it failed to open the screen
device) may ignore even SIGKILL — it clears on logout/reboot. Never SIGKILL a
healthy recording (corrupts the file).

## 3. Stale flags + other jobs

- `live_vision`: `.live_vision.pid` and `.live_eye_paused` — if the PID is dead,
  remove them. `live_vision.py` at high CPU is expected during CV inference.
- Disk: `df -h .` — `recordings/` and `exports/` grow fast.

## 4. Streamlit greyed out but server alive

If `curl http://127.0.0.1:8501/healthz` returns 200 but the window is grey, the
**client socket is stale, not the server**. Open a fresh browser tab
(`open http://127.0.0.1:8501`) rather than restarting — restarting kills the
audio tracker too. Confirm the server truly accepts sockets with a WebSocket
handshake to `/_stcore/stream` (expect `101 Switching Protocols`).

## Principle

Prefer the least-destructive fix. Recordings are data: finalize them, don't
hard-kill. Don't restart the whole stack mid-match just to recover the UI.
