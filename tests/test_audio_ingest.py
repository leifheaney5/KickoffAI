import audio_ingest as AI


def test_learned_corrections_apply_with_boundaries_and_usage(tmp_path):
    path = tmp_path / "corrections.json"
    AI.add_learned_correction("corn her", "corner", path=str(path))

    fixed, applied = AI.apply_learned_corrections(
        "home corn her but not acorn herbal", path=str(path))

    assert fixed == "home corner but not acorn herbal"
    assert applied == [{"heard": "corn her", "intended": "corner", "count": 1}]
    saved = AI.load_corrections(str(path))
    assert saved[0]["uses"] == 1
    assert saved[0]["last_used_at"]


def test_review_record_round_trip_and_event_lookup(tmp_path):
    path = tmp_path / "audio_reviews.json"
    record = AI.make_review_record(
        timestamp="2026-06-24T19:00:00+00:00",
        match_time="12:00",
        event_timestamp="evt-1",
        audio="review_audio/a.wav",
        raw_text="corn her",
        corrected_text="corner",
        suggested_text="Home corner",
        parsed_event={"team": "Home", "action": "corner"},
        status="pending",
        reason="ollama+fallback",
        latency_ms=42,
    )

    AI.append_review(record, str(path))
    assert AI.review_for_event("evt-1", str(path))["suggested_text"] == "Home corner"

    AI.update_review_for_event("evt-1", {"status": "approved"}, str(path))
    assert AI.review_for_event("evt-1", str(path))["status"] == "approved"


def test_load_corrections_caches_until_file_changes(tmp_path):
    path = str(tmp_path / "corrections.json")
    AI.add_learned_correction("corn her", "corner", path=path)

    first = AI.load_corrections(path)
    # No file change -> same cached list object is returned (no re-read).
    assert AI.load_corrections(path) is first

    AI.add_learned_correction("gold", "goal", path=path)
    reloaded = AI.load_corrections(path)
    assert {c["heard"] for c in reloaded} == {"corn her", "gold"}


def test_suggested_text_formats_event():
    assert AI.suggested_text({
        "team": "Away",
        "player": "#10",
        "action": "shot",
        "result": "blocked",
        "location": "box",
    }) == "Away #10 shot blocked from box"

