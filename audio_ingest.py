#!/usr/bin/env python3
"""
Audio ingest sidecars for Kickoff Pulse.

Keeps reviewable audio/transcript records and user-approved correction phrases
in small local JSON files, mirroring the app's existing file-based state style.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone

import control

AUDIO_REVIEWS_FILE = os.environ.get(
    "KICKOFF_AUDIO_REVIEWS_FILE", "audio_reviews.jsonl")
REVIEW_AUDIO_DIR = os.environ.get("KICKOFF_REVIEW_AUDIO_DIR", "review_audio")
CORRECTIONS_FILE = os.environ.get("KICKOFF_CORRECTIONS_FILE", "corrections.json")

# Cap on saved review-audio clips. The dir grows by one WAV per logged/ignored
# phrase, so an unbounded match fills the disk; pruning keeps the newest plus any
# clip still attached to an un-reviewed ("pending") event. 0 disables pruning.
REVIEW_AUDIO_MAX = int(os.environ.get("KICKOFF_REVIEW_AUDIO_MAX", "600"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "").strip("_")
    return value[:80] or "audio"


def _read_list(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def _write_list(path: str, data: list) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        control.atomic_replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# --------------------------------------------------------------------------- #
# Review records (append-only JSON Lines)
# --------------------------------------------------------------------------- #
# Each logged or updated record is one appended line, so the hot transcription
# loop never rewrites the whole file. The old JSON-array store cost O(n) per
# append and O(n^2) over a match (a review is written for every event AND every
# ignored blip). Readers collapse lines by id, last write winning, so an update
# is just another appended (partial) line.
def _reviews_path(path: str = None) -> str:
    return path or AUDIO_REVIEWS_FILE


def _append_review_line(path: str, record: dict) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _rewrite_reviews(path: str, reviews: list) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for rec in reviews:
                fh.write(json.dumps(rec) + "\n")
        control.atomic_replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _migrate_legacy_reviews(path: str) -> None:
    """One-time fold of a legacy JSON-array file into the JSONL store."""
    if os.path.exists(path) or not path.endswith(".jsonl"):
        return
    legacy = path[:-1]  # "audio_reviews.jsonl" -> "audio_reviews.json"
    if os.path.exists(legacy):
        data = _read_list(legacy)
        if data:
            _rewrite_reviews(path, data)


def load_reviews(path: str = None) -> list:
    path = _reviews_path(path)
    _migrate_legacy_reviews(path)
    if not os.path.exists(path):
        return []
    merged: dict = {}
    order: list = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue  # skip a torn/partial line rather than fail
                if not isinstance(rec, dict):
                    continue
                rid = rec.get("id") or f"_anon_{len(order)}"
                if rid in merged:
                    merged[rid].update(rec)  # later line patches the earlier one
                else:
                    merged[rid] = rec
                    order.append(rid)
    except OSError:
        return []
    return [merged[r] for r in order]


def save_reviews(reviews: list, path: str = None) -> None:
    """Compact the store to one line per record (migration / maintenance)."""
    _rewrite_reviews(_reviews_path(path), reviews)


def review_for_event(event_timestamp: str, path: str = None) -> dict | None:
    if not event_timestamp:
        return None
    for review in reversed(load_reviews(path)):
        if review.get("event_timestamp") == event_timestamp:
            return review
    return None


def append_review(record: dict, path: str = None) -> dict:
    path = _reviews_path(path)
    _migrate_legacy_reviews(path)
    _append_review_line(path, record)
    return record


def update_review(review_id: str, updates: dict, path: str = None) -> bool:
    if not review_id:
        return False
    for review in load_reviews(path):
        if review.get("id") == review_id:
            _append_review_line(_reviews_path(path), {"id": review_id, **updates})
            return True
    return False


def update_review_for_event(event_timestamp: str, updates: dict,
                            path: str = None) -> bool:
    if not event_timestamp:
        return False
    for review in reversed(load_reviews(path)):
        if review.get("event_timestamp") == event_timestamp:
            patch = {"id": review.get("id"),
                     "event_timestamp": event_timestamp, **updates}
            _append_review_line(_reviews_path(path), patch)
            return True
    return False


def make_review_record(*, timestamp: str, match_time: str,
                       event_timestamp: str | None, audio: str | None,
                       raw_text: str | None, corrected_text: str | None,
                       suggested_text: str | None, parsed_event: dict | None,
                       status: str, reason: str | None,
                       latency_ms: int | None) -> dict:
    base = timestamp or _now_iso()
    return {
        "id": f"rev_{_safe_slug(base)}",
        "timestamp": base,
        "match_time": match_time,
        "event_timestamp": event_timestamp,
        "audio": audio,
        "raw_text": raw_text,
        "corrected_text": corrected_text,
        "suggested_text": suggested_text,
        "parsed_event": parsed_event or {},
        "status": status,
        "reason": reason,
        "latency_ms": latency_ms,
    }


def suggested_text(event: dict) -> str:
    if not event:
        return ""
    parts = [
        event.get("team"),
        event.get("player"),
        event.get("action"),
        event.get("result"),
    ]
    text = " ".join(str(p).strip() for p in parts if p)
    location = (event.get("location") or "").strip()
    if location:
        text = f"{text} from {location}" if text else location
    return text


def save_review_audio(audio, write_wav, timestamp: str = None) -> str | None:
    """Persist a SpeechRecognition AudioData clip and return its relative path."""
    if audio is None:
        return None
    os.makedirs(REVIEW_AUDIO_DIR, exist_ok=True)
    stamp = _safe_slug(timestamp or _now_iso())
    path = os.path.join(REVIEW_AUDIO_DIR, f"review_{stamp}.wav")
    write_wav(audio, path)
    return path


def prune_review_audio(max_clips: int = None, keep_statuses=("pending",),
                       reviews_path: str = None) -> int:
    """Cap the review-audio directory, deleting the oldest clips first.

    Clips attached to a review whose status is in ``keep_statuses`` (by default
    the still-unreviewed "pending" events) are protected, so the noisy
    "ignored"/"calibration" clips are pruned first. Returns the count removed.
    """
    max_clips = REVIEW_AUDIO_MAX if max_clips is None else max_clips
    if max_clips <= 0 or not os.path.isdir(REVIEW_AUDIO_DIR):
        return 0

    protected = set()
    for review in load_reviews(reviews_path):
        if review.get("status") in keep_statuses and review.get("audio"):
            protected.add(os.path.abspath(review["audio"]))

    clips = []
    for name in os.listdir(REVIEW_AUDIO_DIR):
        if not name.endswith(".wav"):
            continue
        full = os.path.join(REVIEW_AUDIO_DIR, name)
        if os.path.abspath(full) in protected:
            continue
        try:
            clips.append((os.path.getmtime(full), full))
        except OSError:
            continue
    clips.sort()  # oldest first

    # Protected clips count toward the budget so the total stays under the cap.
    over = len(clips) - max(max_clips - len(protected), 0)
    removed = 0
    for _mtime, full in clips[:max(over, 0)]:
        try:
            os.remove(full)
            removed += 1
        except OSError:
            pass
    return removed


# --------------------------------------------------------------------------- #
# Learned corrections
# --------------------------------------------------------------------------- #
# Parsed corrections are cached and only re-read when the file's mtime changes,
# so the hot transcription loop does no disk I/O unless a correction was edited.
_corrections_cache = {"path": None, "mtime": None, "data": []}


def load_corrections(path: str = None) -> list:
    p = path or CORRECTIONS_FILE
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        mtime = None
    cache = _corrections_cache
    if cache["path"] == p and cache["mtime"] == mtime:
        return cache["data"]
    data = _read_list(p)
    cache.update(path=p, mtime=mtime, data=data)
    return data


def save_corrections(corrections: list, path: str = None) -> None:
    p = path or CORRECTIONS_FILE
    _write_list(p, corrections)
    # Refresh the cache to the just-written data so the next read skips the disk.
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        mtime = None
    _corrections_cache.update(path=p, mtime=mtime, data=corrections)


def _norm_phrase(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def comparable_text(text: str) -> str:
    return re.sub(r"[^a-z0-9# ]+", "", (text or "").lower()).strip()


def materially_differs(heard: str, intended: str) -> bool:
    return comparable_text(heard) != comparable_text(intended)


def _replacement_pattern(heard: str):
    return re.compile(rf"(?<!\w){re.escape(heard)}(?!\w)", re.I)


def apply_learned_corrections(text: str, *, update_usage: bool = True,
                              path: str = None) -> tuple[str, list]:
    out = text or ""
    corrections = load_corrections(path)
    applied = []
    changed = False
    now = _now_iso()

    for correction in corrections:
        if not correction.get("enabled", True):
            continue
        heard = _norm_phrase(correction.get("heard"))
        intended = _norm_phrase(correction.get("intended"))
        if not heard or not intended or heard == intended:
            continue
        pattern = _replacement_pattern(heard)
        out, count = pattern.subn(intended, out)
        if count:
            applied.append({"heard": heard, "intended": intended, "count": count})
            if update_usage:
                correction["uses"] = int(correction.get("uses") or 0) + count
                correction["last_used_at"] = now
                changed = True

    if changed:
        save_corrections(corrections, path)
    return out, applied


def add_learned_correction(heard: str, intended: str, *, source: str = "timeline",
                           path: str = None) -> dict | None:
    heard = _norm_phrase(heard)
    intended = _norm_phrase(intended)
    if not heard or not intended or not materially_differs(heard, intended):
        return None

    corrections = load_corrections(path)
    now = _now_iso()
    for correction in corrections:
        if (correction.get("heard", "").lower() == heard.lower()
                and correction.get("intended", "").lower() == intended.lower()):
            correction["enabled"] = True
            correction["last_used_at"] = correction.get("last_used_at") or now
            save_corrections(corrections, path)
            return correction

    record = {
        "heard": heard,
        "intended": intended,
        "enabled": True,
        "source": source,
        "uses": 0,
        "created_at": now,
        "last_used_at": None,
    }
    corrections.append(record)
    save_corrections(corrections, path)
    return record


def set_correction_enabled(index: int, enabled: bool, path: str = None) -> bool:
    corrections = load_corrections(path)
    if index < 0 or index >= len(corrections):
        return False
    corrections[index]["enabled"] = bool(enabled)
    save_corrections(corrections, path)
    return True


def delete_correction(index: int, path: str = None) -> bool:
    corrections = load_corrections(path)
    if index < 0 or index >= len(corrections):
        return False
    corrections.pop(index)
    save_corrections(corrections, path)
    return True

