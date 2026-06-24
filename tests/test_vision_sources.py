"""Tests for resolving files, direct streams, and YouTube URLs."""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_resolve_local_file_and_camera_sources():
    from vision.sources import resolve_video_source

    file_source = resolve_video_source("match.mp4")
    camera_source = resolve_video_source(0)

    assert file_source.kind == "file"
    assert file_source.capture_source == "match.mp4"
    assert camera_source.kind == "camera"
    assert camera_source.capture_source == 0


def test_resolve_direct_stream_url_without_extraction():
    from vision.sources import is_url, is_youtube_url, resolve_video_source

    url = "https://cdn.example.com/live/team.m3u8"
    resolved = resolve_video_source(url)

    assert is_url(url)
    assert not is_youtube_url(url)
    assert resolved.kind == "url"
    assert resolved.capture_source == url


def test_resolve_youtube_url_with_yt_dlp(monkeypatch):
    calls = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            calls["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def extract_info(self, url, download=False):
            calls["url"] = url
            calls["download"] = download
            return {
                "title": "Team Live",
                "is_live": True,
                "webpage_url": url,
                "url": "https://manifest.example.com/live.m3u8",
            }

    monkeypatch.setitem(
        sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)
    )

    from vision.sources import is_youtube_url, resolve_video_source

    url = "https://www.youtube.com/live/abc123"
    resolved = resolve_video_source(url)

    assert is_youtube_url(url)
    assert calls["url"] == url
    assert calls["download"] is False
    assert "m3u8" in calls["opts"]["format"]
    assert resolved.kind == "youtube"
    assert resolved.title == "Team Live"
    assert resolved.is_live is True
    assert resolved.capture_source == "https://manifest.example.com/live.m3u8"
