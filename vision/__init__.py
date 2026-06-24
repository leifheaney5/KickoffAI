#!/usr/bin/env python3
"""Kickoff Pulse — local computer-vision pipeline ("the Eye").

A fully-local soccer video analytics stack that turns raw match footage into
structured tactical data with no external API calls:

    video frame
        |
        v
    detection.Detector          YOLO (player / ball / referee / jersey_number)
        |  detections + track ids (BoT-SORT / ByteTrack)
        v
    tracking.IdentityManager    identity permanence across occlusion / panning
        |
        v
    homography.PitchHomography  pixels -> pitch (metres + 0..100 normalised)
        |
        v
    teams.TeamClassifier/OCR    shirt-colour K-Means + jersey-number OCR
        |
        v
    heuristics.StatsEngine      possession + passing state machine
        |
        v
    pipeline.MatchAnalyzer      orchestration -> match_stats.json

Heavy optional backends (ultralytics, torch, easyocr, scikit-learn,
opencv-python) are imported lazily by the modules that need them, so importing
this package is cheap and the pure geometry / heuristics stay test-friendly.
"""

from .config import PipelineConfig, canonical_class
from .detection import Detection, Detector
from .heuristics import BallObs, PlayerObs, StatsEngine
from .homography import PitchHomography
from .pipeline import MatchAnalyzer, analyze
from .schema import (
    BallState,
    FrameRecord,
    MatchStats,
    PassEvent,
    PlayerState,
    PossessionSummary,
)
from .sources import (
    ResolvedVideoSource,
    SourceResolutionError,
    is_url,
    is_youtube_url,
    resolve_video_source,
)
from .teams import JerseyOCR, TeamClassifier
from .tracking import IdentityManager

__version__ = "1.3.0"

__all__ = [
    "PipelineConfig",
    "canonical_class",
    "Detector",
    "Detection",
    "IdentityManager",
    "PitchHomography",
    "TeamClassifier",
    "JerseyOCR",
    "StatsEngine",
    "PlayerObs",
    "BallObs",
    "MatchAnalyzer",
    "analyze",
    "MatchStats",
    "FrameRecord",
    "BallState",
    "PlayerState",
    "PassEvent",
    "PossessionSummary",
    "ResolvedVideoSource",
    "SourceResolutionError",
    "is_url",
    "is_youtube_url",
    "resolve_video_source",
]
