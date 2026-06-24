#!/usr/bin/env python3
"""Kickoff Pulse — vision pipeline configuration.

A single, well-documented place for every tunable knob in the computer-vision
stack. Everything is a plain dataclass so it is trivial to construct in code,
override from the CLI, or populate from environment variables.

No heavy dependencies are imported here on purpose: importing this module is
cheap and side-effect free.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# --------------------------------------------------------------------------- #
# Canonical detection labels.
#
# The pipeline reasons about four canonical classes. A fine-tuned soccer model
# is expected to emit these names directly, but we also alias the relevant COCO
# names so a stock `yolov8x.pt` produces *something* useful out of the box
# (players + ball), degrading gracefully where referee / number are missing.
# --------------------------------------------------------------------------- #
PLAYER = "player"
BALL = "ball"
REFEREE = "referee"
JERSEY = "jersey_number"

CANONICAL_CLASSES = (PLAYER, BALL, REFEREE, JERSEY)

CLASS_ALIASES = {
    # players
    "player": PLAYER,
    "players": PLAYER,
    "person": PLAYER,        # COCO
    "goalkeeper": PLAYER,
    "keeper": PLAYER,
    "gk": PLAYER,
    # ball
    "ball": BALL,
    "sports ball": BALL,     # COCO
    "football": BALL,
    "soccer ball": BALL,
    # referee
    "referee": REFEREE,
    "ref": REFEREE,
    "official": REFEREE,
    # jersey number
    "jersey_number": JERSEY,
    "jersey number": JERSEY,
    "number": JERSEY,
    "shirt_number": JERSEY,
}


def canonical_class(name: object) -> Optional[str]:
    """Map an arbitrary model class name onto one of the canonical labels.

    Returns ``None`` for classes we do not care about (e.g. COCO's "car").
    """
    return CLASS_ALIASES.get(str(name).strip().lower())


# Ultralytics ships these tracker configs by name; we expose a friendly alias.
_TRACKER_YAML = {
    "botsort": "botsort.yaml",
    "bot-sort": "botsort.yaml",
    "bytetrack": "bytetrack.yaml",
    "byte-track": "bytetrack.yaml",
}


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class PipelineConfig:
    """All tunable parameters for a single match-analysis run."""

    # --- Model / IO ------------------------------------------------------- #
    model_path: str = "yolov8x.pt"
    output_path: str = "match_stats.json"
    # "" lets Ultralytics auto-select; otherwise "cpu", "cuda", "0", "mps", ...
    device: str = ""
    tracker: str = "botsort"          # "botsort" | "bytetrack"

    # --- Roboflow detection backend (optional) --------------------------- #
    # When set (e.g. "football-players-detection-3zvbc/12"), detection runs via
    # a Roboflow model instead of local Ultralytics, paired with ByteTrack ids.
    roboflow_model: str = ""
    roboflow_api_url: str = "https://serverless.roboflow.com"
    roboflow_api_key: str = ""        # falls back to ROBOFLOW_API_KEY env

    # --- Sampling / performance ------------------------------------------ #
    # Process one of every `frame_stride` frames (3 -> 30fps source becomes
    # ~10fps sampled, matching the JSON schema's "10_fps").
    frame_stride: int = 3
    detection_conf: float = 0.25
    detection_imgsz: int = 1280
    max_seconds: float = 0.0          # 0 = whole video (otherwise a debug cap)

    # --- Pitch geometry (FIFA standard, metres) -------------------------- #
    pitch_length_m: float = 105.0
    pitch_width_m: float = 68.0
    # Which way the Home side attacks along the pitch X axis. Used to give the
    # "forward" direction a meaning for through-ball classification.
    home_attacks_positive_x: bool = True

    # --- Possession heuristic -------------------------------------------- #
    possession_radius_m: float = 1.5
    possession_frames: int = 15       # consecutive *sampled* frames

    # --- Passing heuristic ----------------------------------------------- #
    max_flight_seconds: float = 4.0
    min_pass_distance_m: float = 3.0
    through_ball_min_distance_m: float = 18.0
    through_ball_space_m: float = 4.0   # clear space around receiver -> "through"
    lofted_speed_mps: float = 11.0
    lofted_missing_frames: int = 2      # ball undetected mid-flight -> "lofted"

    # --- Identity permanence (re-ID) ------------------------------------- #
    # Gate distance in normalised pitch units (0..100). A vanished track may be
    # reclaimed if it reappears within this distance of its predicted position.
    reid_gate_norm: float = 6.0
    reid_max_lost_frames: int = 45      # sampled frames a track may be absent

    # --- Team classification / OCR --------------------------------------- #
    ocr_enabled: bool = True
    ocr_min_conf: float = 0.40
    use_gpu_ocr: bool = False
    team_fit_min_samples: int = 40      # torso crops before K-Means is fit
    swap_teams: bool = False            # flip the arbitrary cluster->side map

    # --- Output volume ---------------------------------------------------- #
    max_frames_recorded: int = 0        # 0 = keep every processed frame

    # --- Live source resilience (HLS / RTSP streams, e.g. Veo) ----------- #
    # A live network feed can stall or drop briefly mid-match. Rather than ending
    # the session on the first failed read, reconnect and resume from the live
    # edge so a 90-minute game survives transient network blips.
    live_reconnect: bool = True
    live_reconnect_attempts: int = 5      # tries per stall before giving up
    live_reconnect_backoff: float = 1.0   # base seconds between tries (linear)
    live_max_reconnects: int = 200        # total reconnects before stopping
    # FFmpeg options OpenCV passes when opening a network stream: ffmpeg's own
    # segment-level reconnect plus a read timeout, so a stalled socket retries
    # instead of hanging forever. Empty -> DEFAULT_FFMPEG_CAPTURE_OPTIONS.
    ffmpeg_capture_options: str = ""

    # --- Visualisation ---------------------------------------------------- #
    show: bool = False                  # cv2.imshow debug overlay

    def __post_init__(self) -> None:
        self.frame_stride = max(1, int(self.frame_stride))
        self.possession_frames = max(1, int(self.possession_frames))
        if not self.roboflow_api_key:
            self.roboflow_api_key = os.environ.get("ROBOFLOW_API_KEY", "")
        if self.tracker.strip().lower() not in _TRACKER_YAML:
            raise ValueError(
                f"Unknown tracker {self.tracker!r}; "
                f"expected one of {sorted(set(_TRACKER_YAML))}"
            )

    # ------------------------------------------------------------------ #
    @property
    def tracker_yaml(self) -> str:
        """The Ultralytics tracker config filename for `model.track(...)`."""
        return _TRACKER_YAML[self.tracker.strip().lower()]

    def sampled_fps(self, source_fps: float) -> float:
        """Effective frame rate after stride-based skipping."""
        if source_fps <= 0:
            return 0.0
        return source_fps / self.frame_stride

    def sampled_fps_label(self, source_fps: float) -> str:
        """Schema-friendly label, e.g. ``"10_fps"``."""
        return f"{self.sampled_fps(source_fps):g}_fps"

    @classmethod
    def from_env(cls, **overrides) -> "PipelineConfig":
        """Build a config from `KICKOFF_VISION_*` env vars, then apply overrides.

        Explicit keyword overrides always win over the environment, which in
        turn wins over the dataclass defaults.
        """
        cfg = cls(
            model_path=_env("KICKOFF_VISION_MODEL", cls.model_path),
            output_path=_env("KICKOFF_VISION_OUTPUT", cls.output_path),
            device=_env("KICKOFF_VISION_DEVICE", cls.device),
            tracker=_env("KICKOFF_VISION_TRACKER", cls.tracker),
            frame_stride=_env_int("KICKOFF_VISION_STRIDE", cls.frame_stride),
            detection_conf=_env_float("KICKOFF_VISION_CONF", cls.detection_conf),
            ocr_enabled=_env_bool("KICKOFF_VISION_OCR", cls.ocr_enabled),
            use_gpu_ocr=_env_bool("KICKOFF_VISION_OCR_GPU", cls.use_gpu_ocr),
            show=_env_bool("KICKOFF_VISION_SHOW", cls.show),
        )
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        cfg.__post_init__()
        return cfg
