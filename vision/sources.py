#!/usr/bin/env python3
"""Video source resolution for files, direct streams, and YouTube URLs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


class SourceResolutionError(RuntimeError):
    """Raised when a user-facing video source cannot be resolved for OpenCV."""


@dataclass(frozen=True)
class ResolvedVideoSource:
    """A source after any URL extraction needed before opening with OpenCV."""

    original: Any
    capture_source: Any
    kind: str
    title: str = ""
    is_live: bool = False
    webpage_url: str = ""


_URL_SCHEMES = {"http", "https", "rtsp", "rtmp", "udp", "tcp"}
_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "gaming.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "youtu.be",
    "www.youtu.be",
}


def is_url(source: Any) -> bool:
    """True when ``source`` looks like a network video source."""
    if not isinstance(source, str):
        return False
    parsed = urlparse(source.strip())
    return parsed.scheme.lower() in _URL_SCHEMES and bool(parsed.netloc)


def is_youtube_url(source: Any) -> bool:
    """True for normal YouTube watch/live/short URLs and youtu.be links."""
    if not is_url(source):
        return False
    host = urlparse(str(source).strip()).hostname or ""
    host = host.lower()
    return host in _YOUTUBE_HOSTS or host.endswith(".youtube.com")


def resolve_video_source(source: Any) -> ResolvedVideoSource:
    """Resolve ``source`` to something ``cv2.VideoCapture`` can open.

    Local paths and camera indices pass through unchanged. Direct network streams
    (HLS, RTSP, RTMP, HTTPS media URLs) also pass through. YouTube pages need a
    short yt-dlp extraction step to obtain the temporary media/HLS URL.
    """
    if isinstance(source, str):
        source = source.strip()
    if not is_url(source):
        kind = "camera" if isinstance(source, int) else "file"
        return ResolvedVideoSource(source, source, kind)
    if is_youtube_url(source):
        return resolve_youtube_source(str(source))
    return ResolvedVideoSource(source, source, "url", webpage_url=str(source))


def resolve_youtube_source(url: str) -> ResolvedVideoSource:
    """Resolve a YouTube watch/live URL into a direct OpenCV-readable URL."""
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise SourceResolutionError(
            "YouTube URL support needs yt-dlp. Install the vision extras again: "
            "pip install -r vision/requirements.txt"
        ) from exc

    # Prefer HLS for live streams because OpenCV's FFmpeg backend can follow the
    # playlist, but keep a generic best-video fallback for ordinary YouTube clips.
    opts = {
        "format": "bestvideo[protocol^=m3u8]/best[protocol^=m3u8]/bestvideo/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        # YouTube's default "web" client now returns media URLs that 403 for any
        # non-browser fetch (OpenCV/FFmpeg). The android/ios clients hand back
        # URLs that open directly, so prefer them with web as a last resort.
        "extractor_args": {"youtube": {"player_client": ["android", "ios", "web"]}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise SourceResolutionError(f"Could not resolve YouTube URL: {exc}") from exc

    info = _first_video_info(info)
    media_url = info.get("url")
    if not media_url:
        raise SourceResolutionError("yt-dlp did not return a playable media URL.")

    return ResolvedVideoSource(
        original=url,
        capture_source=media_url,
        kind="youtube",
        title=str(info.get("title") or ""),
        is_live=bool(info.get("is_live") or info.get("live_status") == "is_live"),
        webpage_url=str(info.get("webpage_url") or url),
    )


def _first_video_info(info: dict) -> dict:
    """Handle extractors that wrap a video in an ``entries`` list."""
    entries = info.get("entries")
    if entries:
        for entry in entries:
            if entry:
                return entry
    return info


# --------------------------------------------------------------------------- #
# Frame grabbing
#
# Used by the calibration and connection-test flows, which need one still frame
# from a source without standing up the whole pipeline.
# --------------------------------------------------------------------------- #
def grab_frame(source: Any, at_seconds: float = 0.0):
    """Open ``source`` and return ``(frame, width, height, fps)``.

    ``at_seconds`` seeks into a recording before grabbing. Frame 0 of a match
    file is whenever record was pressed -- the camera still being levelled, or
    an empty pitch -- which is a poor frame to calibrate from. Seeking is
    skipped for live sources, where there is nothing to seek within, and lands
    on the nearest preceding keyframe rather than the exact second; for a fixed
    camera that makes no difference, since the view does not change.

    Returns ``(None, w, h, fps)`` if no frame arrives.
    """
    import cv2

    resolved = resolve_video_source(source)
    cap = cv2.VideoCapture(resolved.capture_source)
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if at_seconds > 0 and resolved.kind == "file":
            cap.set(cv2.CAP_PROP_POS_MSEC, float(at_seconds) * 1000.0)
        # A network stream often needs a few reads before it returns a frame.
        for _ in range(8):
            ok, frame = cap.read()
            if ok and frame is not None:
                return frame, w or frame.shape[1], h or frame.shape[0], fps
        return None, w, h, fps
    finally:
        cap.release()


def file_duration_seconds(source: Any) -> float:
    """Length of a recorded source in seconds, or 0.0 if it cannot be read."""
    try:
        import cv2

        cap = cv2.VideoCapture(str(source))
        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            return count / fps if fps > 0 and count > 0 else 0.0
        finally:
            cap.release()
    except Exception:
        return 0.0
