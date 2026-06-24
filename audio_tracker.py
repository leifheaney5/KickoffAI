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
import audioop
from collections import Counter
from datetime import datetime, timezone

import requests

import audio_ingest
import control

# --------------------------------------------------------------------------- #
# Configuration (override via environment variables)
# --------------------------------------------------------------------------- #
DATA_FILE = os.environ.get("KICKOFF_DATA_FILE", "match_data.json")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

# Whisper model size. "medium.en" favors accurate short soccer commands over
# minimum latency. Override WHISPER_MODEL / WHISPER_MLX_MODEL for speed tests.
WHISPER_OPENAI_MODEL = os.environ.get("WHISPER_MODEL", "medium.en")
# mlx-whisper expects a HuggingFace repo id.
WHISPER_MLX_MODEL = os.environ.get(
    "WHISPER_MLX_MODEL", "mlx-community/whisper-medium.en-mlx"
)

# Microphone selection. Unset = the system default input. Set to a device index
# or a name substring (e.g. "AirPods") to pin a specific mic.
MIC_SELECT = os.environ.get("KICKOFF_MIC")

# --- Noise gating ----------------------------------------------------------- #
# Two layers keep background noise out of the log:
#   1. The microphone only "hears" sound clearly above the room ambience.
#   2. Whisper output is rejected unless it looks like real, confident speech.
# Every knob is overridable via the environment so a noisy venue can be tuned.
#
# Mic energy: dynamic auto-lowering is OFF by default (in a quiet room it keeps
# dropping until it triggers on hum). The "background block-out" slider in the
# dashboard drives the threshold live each loop (see control.gate_to_threshold).
# KICKOFF_ENERGY_THRESHOLD pins a fixed value and ignores the slider.
_ENV_ENERGY = os.environ.get("KICKOFF_ENERGY_THRESHOLD")  # fixed value if set
ENERGY_THRESHOLD = float(_ENV_ENERGY) if _ENV_ENERGY else None
DYNAMIC_ENERGY = os.environ.get("KICKOFF_DYNAMIC_ENERGY", "0") == "1"
PAUSE_THRESHOLD = float(os.environ.get("KICKOFF_PAUSE_THRESHOLD", "0.8"))
PHRASE_TIME_LIMIT = float(os.environ.get("KICKOFF_PHRASE_TIME_LIMIT", "10"))
POST_SPEECH_PADDING = float(os.environ.get("KICKOFF_POST_SPEECH_PADDING", "0.15"))

# Speech acceptance: ignore too-short blips and low-confidence / repetitive
# transcripts (Whisper's classic hallucinations on near-silence).
MIN_PHRASE_SEC = float(os.environ.get("KICKOFF_MIN_PHRASE_SEC", "0.4"))
MIN_WORDS = int(os.environ.get("KICKOFF_MIN_WORDS", "2"))
NO_SPEECH_MAX = float(os.environ.get("KICKOFF_NO_SPEECH_MAX", "0.6"))
LOGPROB_MIN = float(os.environ.get("KICKOFF_LOGPROB_MIN", "-1.0"))
REPEAT_RATIO = float(os.environ.get("KICKOFF_REPEAT_RATIO", "0.6"))
UNIQUE_MIN = float(os.environ.get("KICKOFF_UNIQUE_MIN", "0.35"))

# Whole-transcript fillers Whisper invents from noise/silence.
HALLUCINATION_PHRASES = {
    "you", "thank you", "thanks for watching", "thanks for watching!",
    "bye", "okay", "ok", "so", "yeah", "uh", "um", "hmm", "mm",
    "please subscribe", "subtitles by the amara.org community",
}

# Single-word calls a commentator genuinely shouts — exempt from the
# two-word minimum so a lone "Goal!" / "Corner!" still counts.
SOCCER_KEYWORDS = {
    "goal", "corner", "offside", "penalty", "foul", "save", "saved",
    "card", "yellow", "red", "tackle", "handball", "shot", "block",
    "header", "cross", "substitution", "clearance",
}


# Bias Whisper toward soccer vocabulary so the right words win on close calls
# (e.g. "away team" instead of "la team"). Passed as the decoder's initial_prompt.
INITIAL_PROMPT = os.environ.get(
    "KICKOFF_INITIAL_PROMPT",
    "Live soccer match commentary. The two sides are called Home and Away. "
    "Preserve soccer vocabulary and shirt numbers exactly. Common phrases: "
    "home team, away team, number 4, number 10, pass complete, pass incomplete, "
    "shot, shot on target, blocked shot, save, keeper save, tackle, foul, goal, "
    "corner, corner kick, offside, header, cross, dribble, clearance, "
    "interception, yellow card, red card, handball, penalty, substitution, "
    "throw-in, goal kick, left wing, right wing, midfield, penalty box.")

# Post-transcription fixes for words Whisper reliably mangles. Applied with
# word boundaries, case-insensitively, before parsing. This is our lightweight
# domain lexicon: Whisper cannot be hotword-trained here, but nudging common
# soccer homophones before intent parsing recovers many otherwise-lost events.
_CORRECTIONS = [
    (r"\b(?:la|le|lay) team\b", "away team"),
    (r"\b(?:a|the) way team\b", "away team"),
    (r"\baway team\b", "away team"),
    (r"\bsave (?:la|le|a|the) way\b", "save away"),
    (r"\b(?:om|ohm|hom|hum|hone) team\b", "home team"),
    (r"\b(number|num|no\.?)\s+(?:to|too)\b", r"\1 2"),
    (r"\b(number|num|no\.?)\s+(?:for|fore)\b", r"\1 4"),
    (r"\b(number|num|no\.?)\s+(?:ate)\b", r"\1 8"),
    (r"\b(number|num|no\.?)\s+(?:won)\b", r"\1 1"),
    (r"\bgold\b", "goal"),
    (r"\bgold kick\b", "goal kick"),
    (r"\bcorn\s+(?:er|her)\b", "corner"),
    (r"\bcoroner\b", "corner"),
    (r"\boff\s+sides?\b", "offside"),
    (r"\boffside[s]?\b", "offside"),
    (r"\bsafe\b(?!\s+pass)", "save"),
    (r"\bshut\b", "shot"),
    (r"\byellow\s+car\b", "yellow card"),
    (r"\bred\s+car\b", "red card"),
    (r"\bhand\s+ball\b", "handball"),
    (r"\bthrow in\b", "throw-in"),
    (r"\bthrow and\b", "throw-in"),
]
_CORRECTIONS = [(re.compile(p, re.I), r) for p, r in _CORRECTIONS]

_NUMBER_WORDS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90,
}
_NUMBER_WORD_RE = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_SPOKEN_NUMBER = re.compile(
    rf"\b(number|num|no\.?|#)\s+"
    rf"(({_NUMBER_WORD_RE})(?:[\s-]+({_NUMBER_WORD_RE}))?)\b",
    re.I,
)


def _parse_spoken_number(words: str):
    parts = [p for p in re.split(r"[\s-]+", words.lower()) if p]
    if not parts or any(p not in _NUMBER_WORDS for p in parts):
        return None
    # "one zero" is common for #10, while "twenty one" should be #21.
    if len(parts) == 2 and 0 < _NUMBER_WORDS[parts[0]] < 10:
        return _NUMBER_WORDS[parts[0]] * 10 + _NUMBER_WORDS[parts[1]]
    return sum(_NUMBER_WORDS[p] for p in parts)


def _normalise_spoken_numbers(text: str) -> str:
    def repl(match):
        number = _parse_spoken_number(match.group(2))
        if number is None:
            return match.group(0)
        marker = "#" if match.group(1) == "#" else match.group(1)
        return f"{marker} {number}"

    return _SPOKEN_NUMBER.sub(repl, text)


def apply_corrections(text: str) -> str:
    """Repair common Whisper mishearings before parsing."""
    out = text or ""
    for pattern, repl in _CORRECTIONS:
        out = pattern.sub(repl, out)
    out, _applied = audio_ingest.apply_learned_corrections(out)
    out = _normalise_spoken_numbers(out)
    return out


# Recognised vocabulary — used to normalise and validate the model's output.
TEAMS = {"home", "away"}
ACTIONS = {"pass", "shot", "tackle", "foul", "goal", "save", "cross", "dribble",
           "card", "corner", "offside", "interception", "clearance", "substitution"}
RESULTS = {"complete", "incomplete", "missed", "blocked", "on target", "scored",
           "saved", "won", "lost", "successful", "unsuccessful", "yellow", "red"}


# --------------------------------------------------------------------------- #
# Speech acceptance gate
# --------------------------------------------------------------------------- #
def is_real_speech(text: str, segments: list):
    """Decide whether a transcript is genuine speech worth logging.

    Returns (ok, reason). Rejects empties, one-word blips, known filler
    hallucinations, runaway repetition, and low-confidence output (high
    no-speech probability or low average log-prob from Whisper's segments).
    """
    t = (text or "").strip()
    if not t:
        return False, "empty"

    words = re.findall(r"[A-Za-z']+", t)
    low = [w.lower() for w in words]
    if len(words) < MIN_WORDS:
        # Allow a single, unambiguous soccer shout ("Goal!"); drop other blips.
        if not (len(words) == 1 and low[0] in SOCCER_KEYWORDS):
            return False, "too short"

    norm = re.sub(r"[^a-z ]+", "", t.lower()).strip()
    if norm in HALLUCINATION_PHRASES:
        return False, "filler"

    # Runaway repetition, both kinds Whisper produces on non-speech:
    #   - one word dominating ("no no no ...")
    #   - a short phrase looping ("I'm the one who knows" x N) -> few unique words
    if len(words) >= 6:
        word, n = Counter(low).most_common(1)[0]
        if n / len(words) > REPEAT_RATIO:
            return False, f"repetition ({word} x{n})"
        if len(set(low)) / len(words) < UNIQUE_MIN:
            return False, "looped phrase"

    # Whisper confidence, when the backend reports per-segment scores.
    if segments:
        worst_no_speech = max(
            (s.get("no_speech_prob", 0.0) for s in segments), default=0.0)
        mean_logprob = sum(
            s.get("avg_logprob", 0.0) for s in segments) / len(segments)
        if worst_no_speech > NO_SPEECH_MAX:
            return False, f"no-speech {worst_no_speech:.2f}"
        if mean_logprob < LOGPROB_MIN:
            return False, f"low-confidence {mean_logprob:.2f}"

    return True, "ok"


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

    # Decoding options shared by both backends. Pinning the language and
    # temperature, and turning OFF condition_on_previous_text, stops Whisper
    # from drifting into the repetition loops it produces on non-speech.
    _OPTS = dict(
        language="en",
        temperature=0.0,
        condition_on_previous_text=False,
        initial_prompt=INITIAL_PROMPT,
        no_speech_threshold=NO_SPEECH_MAX,
        logprob_threshold=LOGPROB_MIN,
        compression_ratio_threshold=2.4,
    )

    def transcribe(self, wav_path: str):
        """Return (text, segments) for a WAV file. Text may be empty."""
        try:
            if self.backend == "mlx-whisper":
                result = self._mlx.transcribe(
                    wav_path, path_or_hf_repo=WHISPER_MLX_MODEL, **self._OPTS
                )
            else:
                result = self._openai_model.transcribe(
                    wav_path, fp16=False, **self._OPTS
                )
            return (result.get("text") or "").strip(), result.get("segments") or []
        except Exception as exc:
            print(f"[ear] transcription error: {exc}", flush=True)
            return "", []


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


def _empty_event() -> dict:
    return {
        "team": None,
        "player": None,
        "action": None,
        "result": None,
        "location": None,
    }


def _has_event_bits(event: dict) -> bool:
    return any(event.get(k) for k in _empty_event())


def _match_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def infer_event_from_text(text: str) -> dict:
    """Best-effort local parser for obvious soccer events.

    This is intentionally small and conservative. It does not replace the LLM
    parser; it fills common action/team/result fields when a corrected transcript
    contains unambiguous soccer vocabulary or when Ollama is unavailable.
    """
    event = _empty_event()
    raw = text or ""
    low = re.sub(r"[^a-z0-9#\s-]+", " ", raw.lower())
    low = re.sub(r"\s+", " ", low).strip()
    if not low:
        return event

    if re.search(r"\bhome(?:\s+team|\s+side)?\b", low):
        event["team"] = "Home"
    elif re.search(r"\baway(?:\s+team|\s+side)?\b", low):
        event["team"] = "Away"

    player = _extract_player_ref(low)
    if player:
        event["player"] = player

    _infer_action_and_result(low, event)
    event["location"] = _infer_location(low)
    return event


def _extract_player_ref(text: str):
    m = re.search(r"\b(?:number|num|no\.?|#)\s*#?\s*(\d{1,3})\b", text, re.I)
    if m:
        return f"#{int(m.group(1))}"
    return None


def _infer_action_and_result(text: str, event: dict) -> None:
    if _match_any(text, [r"\byellow\s+card\b", r"\bbooking\b"]):
        event["action"] = "card"
        event["result"] = "yellow"
        return
    if _match_any(text, [
            r"\bred\s+card\b", r"\bsent\s+off\b", r"\bsecond\s+yellow\b"]):
        event["action"] = "card"
        event["result"] = "red"
        return
    if _match_any(text, [
            r"\bgoal\b(?!\s+kick)", r"\bscores?\b", r"\bscored\b",
            r"\bfinds?\s+the\s+net\b"]):
        event["action"] = "goal"
        event["result"] = "scored"
        return
    if _match_any(text, [
            r"\bcorner\b", r"\bcorner\s+kick\b"]):
        event["action"] = "corner"
        return
    if _match_any(text, [r"\boffside\b"]):
        event["action"] = "offside"
        return
    if _match_any(text, [
            r"\bsubstitution\b", r"\bsubbed\b", r"\bcomes?\s+on\b",
            r"\bcomes?\s+off\b"]):
        event["action"] = "substitution"
        return
    if _match_any(text, [
            r"\bsave\b", r"\bsaved\b", r"\bkeeper\s+stop", r"\bstops?\b"]):
        event["action"] = "save"
        event["result"] = "saved"
        return
    if _match_any(text, [
            r"\bshot\b", r"\bshoots?\b", r"\bstrike\b", r"\beffort\b",
            r"\battempt\b"]):
        event["action"] = "shot"
        if _match_any(text, [r"\bblocked\b", r"\bblock\b"]):
            event["result"] = "blocked"
        elif _match_any(text, [r"\bon\s+target\b", r"\bon\s+goal\b"]):
            event["result"] = "on target"
        elif _match_any(text, [r"\bsaved\b", r"\bkeeper\s+save\b"]):
            event["result"] = "saved"
        elif _match_any(text, [r"\bmiss(?:es|ed)?\b", r"\bwide\b", r"\bover\b"]):
            event["result"] = "missed"
        return
    if _match_any(text, [r"\bfoul\b", r"\bfouled\b", r"\bfree\s+kick\b"]):
        event["action"] = "foul"
        return
    if _match_any(text, [r"\btackle\b", r"\btackles\b", r"\bchallenge\b"]):
        event["action"] = "tackle"
        if _match_any(text, [r"\bwon\b", r"\bwins\b"]):
            event["result"] = "won"
        elif _match_any(text, [r"\blost\b", r"\bloses\b"]):
            event["result"] = "lost"
        return
    if _match_any(text, [r"\binterception\b", r"\bintercepts?\b"]):
        event["action"] = "interception"
        return
    if _match_any(text, [r"\bclearance\b", r"\bclears?\b"]):
        event["action"] = "clearance"
        return
    if _match_any(text, [r"\bcross\b", r"\bcrosses\b"]):
        event["action"] = "cross"
        return
    if _match_any(text, [r"\bdribble\b", r"\bdribbles\b"]):
        event["action"] = "dribble"
        return
    if _match_any(text, [r"\bpass\b", r"\bpasses\b", r"\bpassing\b"]):
        event["action"] = "pass"
        if _match_any(text, [r"\bcomplete\b", r"\bcompleted\b", r"\bconnects\b"]):
            event["result"] = "complete"
        elif _match_any(text, [
                r"\bincomplete\b", r"\bmiss(?:es|ed)?\b",
                r"\bintercept(?:ed|ion)\b"]):
            event["result"] = "incomplete"


def _infer_location(text: str):
    locations = [
        ("left wing", [r"\bleft\s+wing\b", r"\bleft\s+flank\b"]),
        ("right wing", [r"\bright\s+wing\b", r"\bright\s+flank\b"]),
        ("midfield", [r"\bmidfield\b", r"\bmiddle\s+third\b"]),
        ("penalty box", [r"\bpenalty\s+box\b", r"\bbox\b"]),
        ("six-yard box", [r"\bsix\s+yard\s+box\b", r"\bsix-yard\s+box\b"]),
        ("final third", [r"\bfinal\s+third\b"]),
        ("defensive third", [r"\bdefensive\s+third\b"]),
    ]
    for location, patterns in locations:
        if _match_any(text, patterns):
            return location
    return None


def merge_events(primary: dict, fallback: dict) -> dict:
    """Fill gaps in primary with deterministic fallback fields."""
    merged = {**_empty_event(), **(primary or {})}
    fallback = fallback or {}
    for key in _empty_event():
        if not merged.get(key) and fallback.get(key):
            merged[key] = fallback[key]
    return merged


def resolve_event(event: dict, lineups=None) -> dict:
    """Resolve roster-dependent fields on an already-normalised event."""
    if not _has_event_bits(event):
        return {}
    event = {**_empty_event(), **event}
    name, team = control.resolve_player(
        lineups, event.get("player"), event.get("team"))
    event["player"], event["team"] = name, team
    return event


def parse_event(text: str, lineups=None, return_source: bool = False):
    """Send transcript to Ollama and return a normalised event dict, or {}.

    When a lineup is available it is handed to the model as context (so spoken
    shirt numbers come back as names and the side is filled in), and the parsed
    player is resolved against the roster as a deterministic backstop.
    """
    fallback = infer_event_from_text(text)
    system = SYSTEM_PROMPT
    roster = control.roster_prompt(lineups)
    if roster:
        system += (
            "\n\nKNOWN ROSTERS for this match. Map any shirt number you hear to "
            "that player's NAME, prefer outputting the name in \"player\", and use "
            "the roster to decide whether the event is Home or Away:\n" + roster)

    payload = {
        "model": OLLAMA_MODEL,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": system},
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
        event = resolve_event(fallback, lineups)
        return (event, "fallback") if return_source else event
    except (KeyError, ValueError) as exc:
        print(f"[brain] could not parse model output: {exc}", flush=True)
        event = resolve_event(fallback, lineups)
        return (event, "fallback") if return_source else event

    model_event = normalise(event)
    source = "ollama+fallback" if _has_event_bits(fallback) else "ollama"
    event = merge_events(model_event, fallback)
    # Deterministic backstop: map shirt numbers to names and infer the side.
    event = resolve_event(event, lineups)
    return (event, source) if return_source else event


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
    s = _normalise_spoken_numbers(player.strip())
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
def pick_microphone(sr):
    """Open the configured microphone (KICKOFF_MIC) or the system default.

    KICKOFF_MIC may be a device index or a case-insensitive name substring
    (e.g. "AirPods"). Falls back to the default device when unset or unmatched.
    """
    if not MIC_SELECT:
        return sr.Microphone()
    names = sr.Microphone.list_microphone_names()
    idx = None
    if MIC_SELECT.isdigit() and int(MIC_SELECT) < len(names):
        idx = int(MIC_SELECT)
    else:
        idx = next((i for i, n in enumerate(names)
                    if MIC_SELECT.lower() in n.lower()), None)
    if idx is None:
        print(f"[ear] mic '{MIC_SELECT}' not found; using the system default. "
              f"Available inputs: {names}", flush=True)
        return sr.Microphone()
    print(f"[ear] using microphone #{idx}: {names[idx]}", flush=True)
    return sr.Microphone(device_index=idx)


def write_wav(audio, path: str) -> None:
    """Write SpeechRecognition AudioData to a 16-bit mono WAV file."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(audio.sample_width)
        wf.setframerate(audio.sample_rate)
        wf.writeframes(audio.get_raw_data())


def audio_energy(audio):
    try:
        return int(audioop.rms(audio.frame_data, audio.sample_width))
    except Exception:
        return None


def _float_setting(value, default, lo, hi):
    try:
        f = float(value)
    except (TypeError, ValueError):
        f = default
    return max(lo, min(hi, f))


def chunking_config(ctrl=None) -> dict:
    saved = (ctrl or {}).get("audio_chunking") or {}
    return {
        "phrase_time_limit": _float_setting(
            saved.get("phrase_time_limit"), PHRASE_TIME_LIMIT, 2.0, 20.0),
        "pause_threshold": _float_setting(
            saved.get("pause_threshold"), PAUSE_THRESHOLD, 0.25, 2.0),
        "min_phrase_sec": _float_setting(
            saved.get("min_phrase_sec"), MIN_PHRASE_SEC, 0.1, 2.0),
        "post_speech_padding": _float_setting(
            saved.get("post_speech_padding"), POST_SPEECH_PADDING, 0.0, 1.0),
    }


def write_review(*, timestamp: str, match_time: str, event_timestamp,
                 audio, raw_text, corrected_text, event, status: str, reason,
                 latency_ms) -> dict:
    audio_rel = None
    try:
        audio_rel = audio_ingest.save_review_audio(audio, write_wav, timestamp)
    except Exception as exc:
        print(f"[review] could not save audio: {exc}", flush=True)
    record = audio_ingest.make_review_record(
        timestamp=timestamp,
        match_time=match_time,
        event_timestamp=event_timestamp,
        audio=audio_rel,
        raw_text=raw_text,
        corrected_text=corrected_text,
        suggested_text=audio_ingest.suggested_text(event or {}),
        parsed_event=event or {},
        status=status,
        reason=reason,
        latency_ms=latency_ms,
    )
    try:
        return audio_ingest.append_review(record)
    except Exception as exc:
        print(f"[review] could not save review record: {exc}", flush=True)
        return record


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
              "Only simple keyword fallback parsing will run until it is up.",
              flush=True)

    transcriber = Transcriber()
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = DYNAMIC_ENERGY
    initial_chunking = chunking_config(control.load_control())
    recognizer.pause_threshold = initial_chunking["pause_threshold"]
    recognizer.non_speaking_duration = initial_chunking["post_speech_padding"]

    try:
        mic = pick_microphone(sr)
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

    # Set the initial gate. A fixed env value wins; otherwise the dashboard's
    # block-out slider governs it (and keeps governing it live in the loop).
    if ENERGY_THRESHOLD is not None:
        recognizer.energy_threshold = ENERGY_THRESHOLD
        print(f"[ear] mic energy threshold fixed at {ENERGY_THRESHOLD:.0f} "
              f"(KICKOFF_ENERGY_THRESHOLD set).", flush=True)
    else:
        gate = control.load_control().get("noise_gate", control.DEFAULT_NOISE_GATE)
        recognizer.energy_threshold = control.gate_to_threshold(gate)
        print(f"[ear] background block-out {gate}/100 -> energy threshold "
              f"{recognizer.energy_threshold:.0f} (adjust live from the dashboard).",
              flush=True)

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
        "last_raw_heard": None,
        "last_corrected_heard": None,
        "last_ignored_reason": None,
        "last_energy": None,
        "energy_threshold": None,
        "events": len(load_events()),
        "backend": transcriber.backend,
        "chunking": initial_chunking,
    }
    control.save_status(status)

    paused_notice = False
    last_gate = None
    while running["flag"]:
        ctrl = control.load_control()
        chunk_cfg = chunking_config(ctrl)
        recognizer.pause_threshold = chunk_cfg["pause_threshold"]
        recognizer.non_speaking_duration = chunk_cfg["post_speech_padding"]
        status["chunking"] = chunk_cfg

        # Apply the live "background block-out" slider (unless a fixed env
        # threshold is pinned). Updating energy_threshold takes effect on the
        # next listen(), so dragging the slider changes sensitivity instantly.
        if ENERGY_THRESHOLD is None:
            gate = ctrl.get("noise_gate", control.DEFAULT_NOISE_GATE)
            if gate != last_gate:
                recognizer.energy_threshold = control.gate_to_threshold(gate)
                print(f"[ear] block-out set to {gate}/100 -> energy threshold "
                      f"{recognizer.energy_threshold:.0f}", flush=True)
                last_gate = gate
        status["energy_threshold"] = recognizer.energy_threshold
        status["noise_gate"] = ctrl.get("noise_gate", control.DEFAULT_NOISE_GATE)

        # Honour a pause requested from the dashboard: stop logging events.
        if ctrl.get("paused"):
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
                    source, timeout=2,
                    phrase_time_limit=chunk_cfg["phrase_time_limit"]
                )
        except sr.WaitTimeoutError:
            continue  # no speech in this window; keep listening
        except OSError as exc:
            print(f"[ear] microphone read error: {exc}", flush=True)
            time.sleep(0.5)
            continue

        # Drop sub-threshold blips (a cough, a door) before paying for Whisper.
        duration = len(audio.frame_data) / (audio.sample_rate * audio.sample_width)
        energy = audio_energy(audio)
        status["last_energy"] = energy
        if duration < chunk_cfg["min_phrase_sec"]:
            status["last_ignored_reason"] = f"audio too short {duration:.2f}s"
            control.save_status(status)
            continue

        # Transcribe via a temp WAV file.
        started = time.perf_counter()
        tmp_wav = None
        try:
            fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            write_wav(audio, tmp_wav)
            raw_text, segments = transcriber.transcribe(tmp_wav)
        finally:
            if tmp_wav and os.path.exists(tmp_wav):
                os.remove(tmp_wav)

        # Repair common mishearings (Home/Away side names) before anything else.
        text = apply_corrections(raw_text)

        # Stamp the current match-clock reading so reviews/feed/report can show it.
        ctrl = control.load_control()
        main_clk, added, _half = control.clock_label(ctrl["timer"])
        match_time = f"{main_clk}{(' ' + added) if added else ''}"

        # Only log confident, speech-like transcripts — this is what keeps
        # background noise and Whisper hallucinations out of the match log.
        ok, reason = is_real_speech(text, segments)

        # Calibration test mode consumes exactly one phrase and never logs it as
        # a match event. It lets the dashboard show the whole ingest pipeline.
        cal = ctrl.get("calibration_test") or {}
        if cal.get("armed"):
            event, parser_source = ({}, "none")
            if ok:
                event, parser_source = parse_event(
                    text, lineups=ctrl.get("lineups"), return_source=True)
            latency_ms = int((time.perf_counter() - started) * 1000)
            result = {
                "armed": False,
                "requested_at": cal.get("requested_at"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": ok,
                "reason": reason,
                "raw_text": raw_text,
                "corrected_text": text,
                "suggested_text": audio_ingest.suggested_text(event),
                "parsed_event": event,
                "parser_source": parser_source,
                "energy": energy,
                "energy_threshold": recognizer.energy_threshold,
                "latency_ms": latency_ms,
            }
            status["calibration_test"] = result
            ctrl["calibration_test"] = {
                "armed": False,
                "requested_at": cal.get("requested_at"),
                "last_result_at": result["timestamp"],
            }
            control.save_control(ctrl)
            write_review(
                timestamp=result["timestamp"],
                match_time=match_time,
                event_timestamp=None,
                audio=audio,
                raw_text=raw_text,
                corrected_text=text,
                event=event,
                status="calibration",
                reason=reason,
                latency_ms=latency_ms,
            )
            status["last_heard"] = text[:140] if text else None
            status["last_raw_heard"] = raw_text[:140] if raw_text else None
            status["last_corrected_heard"] = text[:140] if text else None
            status["last_ignored_reason"] = None if ok else reason
            control.save_status(status)
            print(f"[calibration] {reason}: {text!r}", flush=True)
            continue

        if not ok:
            if text:
                print(f"[ear] ignored ({reason}): {text[:60]!r}", flush=True)
                write_review(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    match_time=match_time,
                    event_timestamp=None,
                    audio=audio,
                    raw_text=raw_text,
                    corrected_text=text,
                    event=None,
                    status="ignored",
                    reason=reason,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            status["last_heard"] = text[:140] if text else None
            status["last_raw_heard"] = raw_text[:140] if raw_text else None
            status["last_corrected_heard"] = text[:140] if text else None
            status["last_ignored_reason"] = reason
            control.save_status(status)
            continue

        # Thoughts mode: capture the phrase as a free-form note, not an event,
        # and keep its audio clip so it can be played back under Match Insights.
        if ctrl.get("thoughts_mode"):
            now_utc = datetime.now(timezone.utc)
            audio_rel = None
            try:
                os.makedirs(control.NOTES_AUDIO_DIR, exist_ok=True)
                audio_rel = os.path.join(
                    control.NOTES_AUDIO_DIR,
                    f"note_{now_utc.strftime('%Y%m%d_%H%M%S_%f')}.wav")
                write_wav(audio, audio_rel)
            except Exception as exc:
                print(f"[note] could not save audio: {exc}", flush=True)
                audio_rel = None
            note = {
                "timestamp": now_utc.isoformat(),
                "match_time": match_time,
                "text": text,
                "audio": audio_rel,
            }
            control.append_note(note)
            status["last_heard"] = text[:140]
            status["notes"] = len(control.load_notes())
            control.save_status(status)
            print(f"[note] saved: {text!r}", flush=True)
            continue

        print(f"[ear] heard: {text!r}", flush=True)
        status["last_heard"] = text[:140]
        status["last_raw_heard"] = raw_text[:140] if raw_text else None
        status["last_corrected_heard"] = text[:140]
        status["last_ignored_reason"] = None
        control.save_status(status)

        event, parser_source = parse_event(
            text, lineups=ctrl.get("lineups"), return_source=True)
        event_timestamp = datetime.now(timezone.utc).isoformat()
        record = {
            "timestamp": event_timestamp,
            "match_time": match_time,
            "raw_text": raw_text,
            "corrected_text": text,
            "parser_source": parser_source,
            "status": "pending",
            **(event or {
                "team": None, "player": None, "action": None,
                "result": None, "location": None,
            }),
        }
        append_event(record)
        write_review(
            timestamp=datetime.now(timezone.utc).isoformat(),
            match_time=match_time,
            event_timestamp=event_timestamp,
            audio=audio,
            raw_text=raw_text,
            corrected_text=text,
            event={k: record.get(k) for k in (
                "team", "player", "action", "result", "location")},
            status="pending",
            reason=parser_source,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
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
