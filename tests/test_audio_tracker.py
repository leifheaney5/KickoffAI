import json

import pytest
import requests

import audio_tracker as A


def test_apply_corrections_repairs_soccer_homophones_and_numbers():
    text = "La team number ten wins a corn her after a safe"

    fixed = A.apply_corrections(text)

    assert fixed == "away team number 10 wins a corner after a save"


def test_apply_corrections_does_not_turn_safe_pass_into_save():
    text = "home number for with a safe pass"

    fixed = A.apply_corrections(text)

    assert fixed == "home number 4 with a safe pass"
    assert A.infer_event_from_text(fixed)["action"] == "pass"


def test_apply_corrections_order_includes_learned_before_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(A.audio_ingest, "CORRECTIONS_FILE",
                        str(tmp_path / "corrections.json"))
    A.audio_ingest.add_learned_correction("corner", "corner kick")

    fixed = A.apply_corrections("away number ten corn her")

    assert fixed == "away number 10 corner kick"


def test_chunking_config_defaults_and_bounds():
    cfg = A.chunking_config({
        "audio_chunking": {
            "phrase_time_limit": 99,
            "pause_threshold": 0.01,
            "min_phrase_sec": "bad",
            "post_speech_padding": 2,
        }
    })

    assert cfg["phrase_time_limit"] == 20.0
    assert cfg["pause_threshold"] == 0.25
    assert cfg["min_phrase_sec"] == A.MIN_PHRASE_SEC
    assert cfg["post_speech_padding"] == 1.0


def test_infer_event_from_text_extracts_obvious_event_fields():
    text = A.apply_corrections(
        "away number twenty one with a shut on target from the box"
    )

    event = A.infer_event_from_text(text)

    assert event == {
        "team": "Away",
        "player": "#21",
        "action": "shot",
        "result": "on target",
        "location": "penalty box",
    }


def test_infer_event_from_text_does_not_count_goal_kick_as_goal():
    text = A.apply_corrections("home gold kick")

    event = A.infer_event_from_text(text)

    assert event["team"] == "Home"
    assert event["action"] is None
    assert event["result"] is None


def test_parse_event_uses_fallback_when_ollama_is_down(monkeypatch):
    def down(*_args, **_kwargs):
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(A.requests, "post", down)
    lineups = {
        "Home": {"players": []},
        "Away": {"players": [{"number": "10", "name": "Ava"}]},
    }
    text = A.apply_corrections("away number ten with a corn her kick")

    event = A.parse_event(text, lineups=lineups)

    assert event["team"] == "Away"
    assert event["player"] == "Ava"
    assert event["action"] == "corner"


def test_parse_event_fills_model_gaps_with_fallback(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            content = {
                "team": "Home",
                "player": "number ten",
                "action": None,
                "result": None,
                "location": None,
            }
            return {"message": {"content": json.dumps(content)}}

    monkeypatch.setattr(A.requests, "post", lambda *_a, **_kw: Response())
    lineups = {
        "Home": {"players": [{"number": "10", "name": "Hannah"}]},
        "Away": {"players": []},
    }
    text = A.apply_corrections("home number ten with a shot on target from box")

    event = A.parse_event(text, lineups=lineups)

    assert event == {
        "team": "Home",
        "player": "Hannah",
        "action": "shot",
        "result": "on target",
        "location": "penalty box",
    }


@pytest.mark.parametrize("phrase", ["gold", "corn her", "off side"])
def test_corrected_single_word_soccer_calls_pass_speech_gate(phrase):
    text = A.apply_corrections(phrase)

    ok, reason = A.is_real_speech(text, [])

    assert (ok, reason) == (True, "ok")
