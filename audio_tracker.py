#!/usr/bin/env python3
"""
Kickoff Pulse — The Ear + The Brain.

Continuously listens to the default microphone, transcribes short bursts of
speech locally (mlx-whisper on Apple Silicon, falling back to openai-whisper),
sends each transcript to a local Ollama model to be parsed into a strict soccer
event, and appends the result to match_data.json.

Run directly for debugging:
    python audio_tracker.py

Or let kickoff.sh manage it as a background process.
"""

import json
import os
import re
import signal
import sys
import tempfile
import time
import wave
from datetime import datetime, timezone

import requests

import control

# --------------------------------------------------------------------------- #
# Configuration (override via environment variables)
# --------------------------------------------------------------------------- #
DATA_FILE = os.environ.get("KICKOFF_DATA_FILE", "match_data.json")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

# Whisper model size. "base.en" is a good speed/accuracy balance on a MacBook Air.
WHISPER_OPENAI_MODEL = os.environ.get("WHISPER_MODEL", "base.en")
# mlx-whisper expects a HuggingFace repo id.
WHISPER_MLX_MODEL = os.environ.get(
    "WHISPER_MLX_MODEL", "mlx-community/whisper-base.en-mlx"
)

# Recognised vocabulary — used to normalise and validate the model's output.
TEAMS = {"home", "away"}
ACTIONS = {"pass", "shot", "tackle", "foul", "goal", "save", "cross", "dribble",
           "card", "corner", "offside", "interception", "clearance", "substitution"}
RESULTS = {"complete", "incomplete", "missed", "blocked", "on target", "scored",
           "saved", "won", "lost", "successful", "unsuccessful", "yellow", "red"}


# --------------------------------------------------------------------------- #
# Transcription backend
# --------------------------------------------------------------------------- #
class Transcriber:
    """Wraps whichever Whisper backend is available."""

    def __init__(self):
        self.backend = None
        self._mlx = None
        self._openai_model = None

        # Prefer the Apple-Silicon-optimised backend.
        try:
            import mlx_whisper  # noqa: F401

            self._mlx = mlx_whisper
            self.backend = "mlx-whisper"
            print(f"[ear] Using mlx-whisper ({WHISPER_MLX_MODEL})", flush=True)
            return
        except Exception as exc:  # pragma: no cover - depends on platform
            print(f"[ear] mlx-whisper unavailable ({exc}); trying openai-whisper",
                  flush=True)

        try:
            import whisper

            print(f"[ear] Loading openai-whisper '{WHISPER_OPENAI_MODEL}' "
                  "(first run downloads the model)...", flush=True)
            self._openai_model = whisper.load_model(WHISPER_OPENAI_MODEL)
            self.backend = "openai-whisper"
            print("[ear] openai-whisper ready", flush=True)
        except Exception as exc:
            print(f"[ear] FATAL: no transcription backend available ({exc}).",
                  flush=True)
            print("[ear] Install one with: pip install mlx-whisper  (or)  "
                  "pip install openai-whisper", flush=True)
            sys.exit(1)

    def transcribe(self, wav_path: str) -> str:
        """Return the transcript for a WAV file (may be empty)."""
        try:
            if self.backend == "mlx-whisper":
                result = self._mlx.transcribe(
                    wav_path, path_or_hf_repo=WHISPER_MLX_MODEL
                )
            else:
                result = self._openai_model.transcribe(wav_path, fp16=False)
            return (result.get("text") or "").strip()
        except Exception as exc:
            print(f"[ear] transcription error: {exc}", flush=True)
            return ""


# --------------------------------------------------------------------------- #
# The Brain — Ollama intent parsing
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = """You are a soccer (football) match data formatter. You do NOT \
chat. You receive a short spoken phrase from a live commentator and convert it \
into a single structured event.

Return ONLY a JSON object with EXACTLY these keys:
  "team":     "Home" or "Away" (or null if not stated)
  "player":   the player's name or number as spoken, else null
  "action":   one of: pass, shot, tackle, foul, goal, save, cross, dribble, \
card, corner, offside, interception, clearance, substitution (or null)
  "result":   the outcome, e.g. complete, incomplete, missed, blocked, on target, \
scored, saved, won, lost; for a card it MUST be "yellow" or "red" (or null)
  "location": where on the pitch, e.g. "left wing", "midfield", "penalty box" (or null)

Rules:
- Use null (not empty strings) for anything not present in the phrase.
- "team" must be exactly "Home" or "Away" when a side is mentioned; map any team \
name, color, or "us/them/they" to the closest of Home/Away, otherwise null.
- A "goal" uses action "goal" AND result "scored".
- A blocked shot uses action "shot", result "blocked".
- "shot on target" / "on goal" uses action "shot", result "on target".
- A goalkeeper stop uses action "save" (result "saved").
- A booking uses action "card" with result "yellow" or "red"; "sent off" / \
"second yellow" is a "red".
- "corner kick" uses action "corner"; "offside" uses action "offside".
- A substitution ("X comes on", "Y is subbed off") uses action "substitution"; \
put the player coming ON in "player" when stated.
- "player" is a name or shirt number only (e.g. "number 10"); a place is a \
location, never a player.
- Output JSON only. No prose, no markdown, no code fences.

Examples:
phrase: "Home number 10 with a shot on target from the box"
{"team":"Home","player":"number 10","action":"shot","result":"on target","location":"box"}
phrase: "Goal for the away team!"
{"team":"Away","player":null,"action":"goal","result":"scored","location":null}
phrase: "Great save by the home keeper"
{"team":"Home","player":null,"action":"save","result":"saved","location":null}
phrase: "Yellow card for the away number 4"
{"team":"Away","player":"number 4","action":"card","result":"yellow","location":null}
phrase: "Home defender sent off, red card"
{"team":"Home","player":null,"action":"card","result":"red","location":null}
phrase: "Corner kick for the away side"
{"team":"Away","player":null,"action":"corner","result":null,"location":null}
phrase: "Substitution for home, number 9 comes on"
{"team":"Home","player":"number 9","action":"substitution","result":null,"location":null}
phrase: "Foul by the home defender on the left wing"
{"team":"Home","player":null,"action":"foul","result":null,"location":"left wing"}
phrase: "Away completes a pass in midfield"
{"team":"Away","player":null,"action":"pass","result":"complete","location":"midfield"}"""


def parse_event(text: str) -> dict:
    """Send transcript to Ollama and return a normalised event dict, or {}."""
    payload = {
        "model": OLLAMA_MODEL,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat", json=payload, timeout=60
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        event = json.loads(content)
    except requests.exceptions.RequestException as exc:
        print(f"[brain] Ollama request failed: {exc}", flush=True)
        return {}
    except (KeyError, ValueError) as exc:
        print(f"[brain] could not parse model output: {exc}", flush=True)
        return {}

    return normalise(event)


def normalise(event: dict) -> dict:
    """Coerce the model's JSON into the canonical schema."""
    if not isinstance(event, dict):
        return {}

    def clean(val):
        if val is None:
            return None
        s = str(val).strip()
        return s if s and s.lower() not in {"null", "none", "n/a", ""} else None

    team = clean(event.get("team"))
    if team:
        t = team.lower()
        team = "Home" if t.startswith("h") else "Away" if t.startswith("a") else None

    action = clean(event.get("action"))
    if action:
        action = action.lower()
        if action not in ACTIONS:
            action = None

    result = clean(event.get("result"))
    if result:
        result = result.lower()

    return {
        "team": team,
        "player": normalise_player(clean(event.get("player"))),
        "action": action,
        "result": result,
        "location": clean(event.get("location")),
    }


def normalise_player(player):
    """Canonicalise player references so '#6', 'number 6', 'no 6' all merge.

    Shirt numbers become '#N'; named players are title-cased.
    """
    if not player:
        return None
    s = player.strip()
    m = re.search(r"(?:number|num|no\.?|#|player)\s*#?\s*(\d{1,3})", s, re.I)
    if m:
        return f"#{int(m.group(1))}"
    if s.isdigit():
        return f"#{int(s)}"
    return s.title()


# --------------------------------------------------------------------------- #
# The Database — append to match_data.json (a JSON array, written atomically)
# --------------------------------------------------------------------------- #
def load_events() -> list:
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def append_event(record: dict) -> None:
    """Append a record and rewrite the file atomically (rename is atomic)."""
    events = load_events()
    events.append(record)
    directory = os.path.dirname(os.path.abspath(DATA_FILE)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(events, fh, indent=2)
        control.atomic_replace(tmp_path, DATA_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# --------------------------------------------------------------------------- #
# The Ear — microphone capture loop
# --------------------------------------------------------------------------- #
def write_wav(audio, path: str) -> None:
    """Write SpeechRecognition AudioData to a 16-bit mono WAV file."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(audio.sample_width)
        wf.setframerate(audio.sample_rate)
        wf.writeframes(audio.get_raw_data())


def main():
    # Graceful shutdown on SIGINT/SIGTERM.
    running = {"flag": True}

    def stop(signum, frame):
        print("\n[ear] shutting down...", flush=True)
        running["flag"] = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        import speech_recognition as sr
    except ImportError:
        print("[ear] FATAL: SpeechRecognition not installed. "
              "Run: pip install SpeechRecognition PyAudio", flush=True)
        sys.exit(1)

    # Verify Ollama is reachable before we start listening.
    try:
        requests.get(f"{OLLAMA_URL}/api/version", timeout=5).raise_for_status()
    except requests.exceptions.RequestException:
        print(f"[brain] WARNING: Ollama not reachable at {OLLAMA_URL}. "
              "Events will be transcribed but not parsed until it is up.",
              flush=True)

    transcriber = Transcriber()
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 0.8  # seconds of silence that ends a phrase

    try:
        mic = sr.Microphone()
    except OSError as exc:
        print(f"[ear] FATAL: cannot open microphone ({exc}).", flush=True)
        print("[ear] Grant microphone permission to your terminal in "
              "System Settings > Privacy & Security > Microphone.", flush=True)
        sys.exit(1)

    print("[ear] Calibrating for ambient noise (stay quiet ~1s)...", flush=True)
    try:
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=1.0)
    except OSError as exc:
        print(f"[ear] FATAL: microphone access denied ({exc}).", flush=True)
        print("[ear] Enable mic permission for your terminal app and retry.",
              flush=True)
        sys.exit(1)

    print("=" * 60, flush=True)
    print(f"  Kickoff Pulse listening  |  transcribe: {transcriber.backend}", flush=True)
    print(f"  model: {OLLAMA_MODEL}  |  data file: {DATA_FILE}", flush=True)
    print("  Speak your play-by-play. Press Ctrl+C to stop.", flush=True)
    print("=" * 60, flush=True)

    # Live status shared with the dashboard's recording indicator.
    now = time.time()
    status = {
        "session_start": now,
        "recording": True,
        "rec_since": now,
        "rec_accum": 0.0,
        "last_event": None,
        "last_heard": None,
        "events": len(load_events()),
        "backend": transcriber.backend,
    }
    control.save_status(status)

    paused_notice = False
    while running["flag"]:
        # Honour a pause requested from the dashboard: stop logging events.
        if control.load_control().get("paused"):
            if not paused_notice:
                print("[ear] recording paused (resume from the dashboard)",
                      flush=True)
                paused_notice = True
                # Bank the active recording time once, on the pause transition.
                if status["recording"] and status["rec_since"]:
                    status["rec_accum"] += time.time() - status["rec_since"]
                status["recording"] = False
                status["rec_since"] = None
            control.save_status(status)  # keep "updated" fresh while paused
            time.sleep(0.4)
            continue
        if paused_notice:
            print("[ear] recording resumed", flush=True)
            paused_notice = False
            status["recording"] = True
            status["rec_since"] = time.time()

        control.save_status(status)  # heartbeat each active cycle

        # Capture one phrase.
        try:
            with mic as source:
                audio = recognizer.listen(
                    source, timeout=2, phrase_time_limit=10
                )
        except sr.WaitTimeoutError:
            continue  # no speech in this window; keep listening
        except OSError as exc:
            print(f"[ear] microphone read error: {exc}", flush=True)
            time.sleep(0.5)
            continue

        # Transcribe via a temp WAV file.
        tmp_wav = None
        try:
            fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            write_wav(audio, tmp_wav)
            text = transcriber.transcribe(tmp_wav)
        finally:
            if tmp_wav and os.path.exists(tmp_wav):
                os.remove(tmp_wav)

        if not text:
            continue  # empty transcription — skip without crashing

        print(f"[ear] heard: {text!r}", flush=True)
        status["last_heard"] = text[:140]
        control.save_status(status)

        event = parse_event(text)
        # Stamp the current match-clock reading so the feed/report can show it.
        ctrl = control.load_control()
        main_clk, added, _half = control.clock_label(ctrl["timer"])
        match_time = f"{main_clk}{(' ' + added) if added else ''}"
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "match_time": match_time,
            "raw_text": text,
            **(event or {
                "team": None, "player": None, "action": None,
                "result": None, "location": None,
            }),
        }
        append_event(record)
        status["last_event"] = record["timestamp"]
        status["events"] = status.get("events", 0) + 1
        control.save_status(status)
        print(f"[brain] logged: {json.dumps({k: record[k] for k in ('team','action','result')})}",
              flush=True)

    # Mark the recording stopped on a clean shutdown.
    if status["recording"] and status["rec_since"]:
        status["rec_accum"] += time.time() - status["rec_since"]
    status["recording"] = False
    status["rec_since"] = None
    control.save_status(status)
    print("[ear] stopped cleanly.", flush=True)


if __name__ == "__main__":
    main()
