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

## 3. The Eye (vision runner)

`vision_runner.json` is the app's view of the Eye; `.live_vision.pid` is the
runner's own. Reconcile them the same way as `recorder.json`:

```bash
.venv/bin/python -c "import vision_runner, json; print(json.dumps(vision_runner.status(), indent=2))"
.venv/bin/python -c "import vision_runner; print(vision_runner.reconcile())"   # clears state pointing at a dead PID
```

Read `health` rather than guessing:

- `ok` — checkpointing normally. High CPU here is expected during inference.
- `starting` — spawned but no frame yet (model load can take ~30-90s on first run).
- `stale` — alive but no checkpoint in 30s: the feed has probably stalled. Check
  `recordings/live_vision.log` and the snapshot age.
- `down` — not running.

Stop it **through the supervisor**, never with a bare `kill -9`: it returns as
soon as the final checkpoint lands, so the match stats are preserved.

```bash
.venv/bin/python -c "import vision_runner; print(vision_runner.stop())"
```

`checkpoint_saved: false` in the result means the stats may be up to one
checkpoint interval (10s) old. Stale `.live_vision.pid` / `.live_eye_paused`
files whose PID is dead can simply be removed.

## 4. Stale flags + disk

- Disk: `df -h .` — `recordings/` and `exports/` grow fast.

## 5. Streamlit greyed out but server alive

If `curl http://127.0.0.1:8501/healthz` returns 200 but the window is grey, the
**client socket is stale, not the server**. Open a fresh browser tab
(`open http://127.0.0.1:8501`) rather than restarting — restarting kills the
audio tracker too. Confirm the server truly accepts sockets with a WebSocket
handshake to `/_stcore/stream` (expect `101 Switching Protocols`).

## Principle

Prefer the least-destructive fix. Recordings are data: finalize them, don't
hard-kill. Don't restart the whole stack mid-match just to recover the UI.
