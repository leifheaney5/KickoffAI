import json

import audio_benchmark as B


class FakeTranscriber:
    def transcribe(self, path):
        return "away number ten corn her", []


def test_run_benchmark_scores_transcript_and_parse(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"fake")
    monkeypatch.setattr(B.audio_tracker.audio_ingest, "CORRECTIONS_FILE",
                        str(tmp_path / "corrections.json"))

    result = B.run_benchmark(
        [{
            "audio": str(audio),
            "expected_text": "away number 10 corner",
            "expected_event": {
                "team": "Away", "player": "#10", "action": "corner",
                "result": None, "location": None,
            },
        }],
        transcriber=FakeTranscriber(),
        parser=lambda text: B.audio_tracker.infer_event_from_text(text),
    )

    row = result["rows"][0]
    assert row["raw_text"] == "away number ten corn her"
    assert row["corrected_text"] == "away number 10 corner"
    assert row["parse_score"] == 1.0
    assert result["successful"] == 1
    # Latency is split into transcribe + parse and the two sum to the total.
    assert row["transcribe_ms"] + row["parse_ms"] == row["latency_ms"]
    assert row["corrected_text_wer"] == 0.0
    assert result["avg_corrected_text_wer"] == 0.0


def test_word_error_rate_counts_word_substitutions():
    assert B.word_error_rate("away number 10 corner", "away number 10 corner") == 0.0
    # one substitution out of four reference words
    assert B.word_error_rate("away number 9 corner", "away number 10 corner") == 0.25


def test_cases_from_manifest(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"audio": "a.wav"}]), encoding="utf-8")

    Args = type("Args", (), {"audio": ["b.wav"], "manifest": str(manifest)})

    cases = B.cases_from_args(Args)

    assert [c["audio"] for c in cases] == ["a.wav", "b.wav"]
