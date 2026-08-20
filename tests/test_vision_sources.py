"""Tests for resolving files, direct streams, and YouTube URLs."""

import importlib.util
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vision import sources


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


# --------------------------------------------------------------------------- #
# Frame grabbing
#
# The calibration flow grabs one still frame. Frame 0 of a match recording is
# whenever record was pressed, so a seek is what makes calibrating from a file
# practical at all.
# --------------------------------------------------------------------------- #
requires_cv2 = pytest.mark.skipif(
    importlib.util.find_spec("cv2") is None, reason="frame grabbing needs OpenCV"
)


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """A 30-second clip whose every frame encodes its own second in blue."""
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    path = str(tmp_path_factory.mktemp("clip") / "match.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (320, 240))
    for i in range(900):
        frame = np.zeros((240, 320, 3), np.uint8)
        frame[:] = (i // 30, 0, 0)
        writer.write(frame)
    writer.release()
    return path


@requires_cv2
def test_grab_frame_returns_geometry_and_a_frame(clip):
    frame, w, h, fps = sources.grab_frame(clip)
    assert frame is not None
    assert (w, h) == (320, 240)
    assert fps == pytest.approx(30.0, abs=0.5)


@requires_cv2
def test_grab_frame_defaults_to_the_very_first_frame(clip):
    frame, _w, _h, _fps = sources.grab_frame(clip)
    assert int(frame[0, 0, 0]) == 0


@requires_cv2
def test_grab_frame_seeks_into_a_recording(clip):
    """Lands on the nearest preceding keyframe, not the exact second.

    That is fine for its purpose -- a fixed camera's view is identical either
    side of the boundary -- but it must land in the right part of the file
    rather than back at the start.
    """
    frame, _w, _h, _fps = sources.grab_frame(clip, at_seconds=25.0)
    assert 15 <= int(frame[0, 0, 0]) <= 25


@requires_cv2
def test_grab_frame_seek_is_monotonic(clip):
    seconds = [
        int(sources.grab_frame(clip, at_seconds=t)[0][0, 0, 0])
        for t in (0.0, 10.0, 20.0)
    ]
    assert seconds == sorted(seconds)
    assert seconds[0] < seconds[-1]


@requires_cv2
def test_grab_frame_ignores_a_seek_on_a_live_source(monkeypatch, clip):
    """Seeking a live stream is meaningless; the request must be dropped."""
    real = sources.resolve_video_source

    def as_live(source):
        resolved = real(source)
        object.__setattr__(resolved, "kind", "url")
        return resolved

    monkeypatch.setattr(sources, "resolve_video_source", as_live)
    frame, _w, _h, _fps = sources.grab_frame(clip, at_seconds=25.0)
    assert int(frame[0, 0, 0]) == 0


@requires_cv2
def test_file_duration_seconds_reads_the_length(clip):
    assert sources.file_duration_seconds(clip) == pytest.approx(30.0, abs=0.5)


@requires_cv2
def test_file_duration_seconds_is_zero_for_junk(tmp_path):
    missing = tmp_path / "nope.mp4"
    assert sources.file_duration_seconds(str(missing)) == 0.0
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video")
    assert sources.file_duration_seconds(str(junk)) == 0.0
