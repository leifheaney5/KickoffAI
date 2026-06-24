#!/usr/bin/env python3
"""
Benchmark Kickoff Pulse audio ingest on recorded WAV clips.

Examples:
    python audio_benchmark.py clip1.wav clip2.wav
    python audio_benchmark.py --manifest audio_benchmark_manifest.json
    python audio_benchmark.py --print-starter
"""

from __future__ import annotations

import argparse
import json
import os
import time
from difflib import SequenceMatcher

import audio_ingest
import audio_tracker


STARTER_CASES = [
    {
        "audio": "",
        "expected_text": "Home number 10 shot on target from the box",
        "expected_event": {
            "team": "Home", "player": "#10", "action": "shot",
            "result": "on target", "location": "penalty box",
        },
    },
    {
        "audio": "",
        "expected_text": "Away number 4 yellow card",
        "expected_event": {
            "team": "Away", "player": "#4", "action": "card",
            "result": "yellow", "location": None,
        },
    },
    {
        "audio": "",
        "expected_text": "Home number 7 completed pass in midfield",
        "expected_event": {
            "team": "Home", "player": "#7", "action": "pass",
            "result": "complete", "location": "midfield",
        },
    },
    {
        "audio": "",
        "expected_text": "Away number 1 save",
        "expected_event": {
            "team": "Away", "player": "#1", "action": "save",
            "result": "saved", "location": None,
        },
    },
    {
        "audio": "",
        "expected_text": "Home corner kick",
        "expected_event": {
            "team": "Home", "player": None, "action": "corner",
            "result": None, "location": None,
        },
    },
    {
        "audio": "",
        "expected_text": "Away number 9 offside",
        "expected_event": {
            "team": "Away", "player": "#9", "action": "offside",
            "result": None, "location": None,
        },
    },
    {
        "audio": "",
        "expected_text": "Home substitution number 12 comes on",
        "expected_event": {
            "team": "Home", "player": "#12", "action": "substitution",
            "result": None, "location": None,
        },
    },
]


def _clean(text: str) -> str:
    return audio_ingest.comparable_text(text or "")


def text_score(actual: str, expected: str | None):
    if not expected:
        return None
    return SequenceMatcher(None, _clean(actual), _clean(expected)).ratio()


def word_error_rate(actual: str, expected: str | None):
    """Word-level WER: edit distance over word sequences / reference length."""
    if not expected:
        return None
    ref = _clean(expected).split()
    hyp = _clean(actual).split()
    if not ref:
        return None
    # Levenshtein distance on word tokens.
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cost = 0 if r == h else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1] / len(ref)


def event_score(actual: dict, expected: dict | None):
    if not expected:
        return None
    keys = ["team", "player", "action", "result", "location"]
    total = len(keys)
    matched = 0
    for key in keys:
        av = actual.get(key)
        ev = expected.get(key)
        if (av or None) == (ev or None):
            matched += 1
    return matched / total


def load_manifest(path: str) -> list:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("manifest must be a JSON list")
    return data


def cases_from_args(args) -> list:
    cases = []
    if args.manifest:
        cases.extend(load_manifest(args.manifest))
    for audio in args.audio:
        cases.append({"audio": audio, "expected_text": None, "expected_event": None})
    return cases


def run_benchmark(cases: list, transcriber=None, parser=None) -> dict:
    transcriber = transcriber or audio_tracker.Transcriber()
    parser = parser or (lambda text: audio_tracker.parse_event(text))
    rows = []

    for case in cases:
        audio = case.get("audio")
        if not audio or not os.path.exists(audio):
            rows.append({
                "audio": audio,
                "error": "missing audio",
                "raw_text": "",
                "corrected_text": "",
                "parsed_event": {},
                "latency_ms": None,
                "transcribe_ms": None,
                "parse_ms": None,
                "raw_text_score": None,
                "corrected_text_score": None,
                "corrected_text_wer": None,
                "parse_score": None,
            })
            continue

        started = time.perf_counter()
        raw, _segments = transcriber.transcribe(audio)
        transcribe_ms = int((time.perf_counter() - started) * 1000)

        parse_started = time.perf_counter()
        corrected = audio_tracker.apply_corrections(raw)
        event = parser(corrected) or {}
        parse_ms = int((time.perf_counter() - parse_started) * 1000)

        rows.append({
            "audio": audio,
            "error": None,
            "raw_text": raw,
            "corrected_text": corrected,
            "parsed_event": event,
            "latency_ms": transcribe_ms + parse_ms,
            "transcribe_ms": transcribe_ms,
            "parse_ms": parse_ms,
            "raw_text_score": text_score(raw, case.get("expected_text")),
            "corrected_text_score": text_score(
                corrected, case.get("expected_text")),
            "corrected_text_wer": word_error_rate(
                corrected, case.get("expected_text")),
            "parse_score": event_score(event, case.get("expected_event")),
        })

    scored = [r for r in rows if not r.get("error")]

    def avg(key):
        vals = [r[key] for r in scored if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    return {
        "count": len(rows),
        "successful": len(scored),
        "avg_latency_ms": avg("latency_ms"),
        "avg_transcribe_ms": avg("transcribe_ms"),
        "avg_parse_ms": avg("parse_ms"),
        "avg_raw_text_score": avg("raw_text_score"),
        "avg_corrected_text_score": avg("corrected_text_score"),
        "avg_corrected_text_wer": avg("corrected_text_wer"),
        "avg_parse_score": avg("parse_score"),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", nargs="*", help="WAV clips to benchmark")
    parser.add_argument("--manifest", help="JSON list with audio/expected fields")
    parser.add_argument("--json", action="store_true", help="Print full JSON")
    parser.add_argument("--print-starter", action="store_true",
                        help="Print a starter manifest template")
    args = parser.parse_args()

    if args.print_starter:
        print(json.dumps(STARTER_CASES, indent=2))
        return

    cases = cases_from_args(args)
    if not cases:
        parser.error("provide WAV paths, --manifest, or --print-starter")

    result = run_benchmark(cases)
    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"Cases: {result['successful']}/{result['count']} usable")
    print(f"Avg latency: {result['avg_latency_ms'] or 0:.0f} ms "
          f"(transcribe {result['avg_transcribe_ms'] or 0:.0f} ms + "
          f"parse {result['avg_parse_ms'] or 0:.0f} ms)")
    if result["avg_raw_text_score"] is not None:
        print(f"Raw transcript score: {result['avg_raw_text_score']:.2%}")
    if result["avg_corrected_text_score"] is not None:
        print(f"Corrected transcript score: "
              f"{result['avg_corrected_text_score']:.2%}")
    if result["avg_corrected_text_wer"] is not None:
        print(f"Corrected transcript WER: {result['avg_corrected_text_wer']:.2%}")
    if result["avg_parse_score"] is not None:
        print(f"Parse score: {result['avg_parse_score']:.2%}")


if __name__ == "__main__":
    main()

