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


# --------------------------------------------------------------------------- #
# Analysis profiles
#
# Inference size, not source resolution, is what decides whether the ball is
# found at all. Three runs over the same 10-minute segment, one variable changed
# at a time; the ball was detected in this share of processed frames:
#
#     360p  source, imgsz 960    ->   2.2%
#     1080p source, imgsz 960    ->   6.6%
#     1080p source, imgsz 1920   ->  33.2%
#
# quality.py grades a run `measured` at 35% ball detection and `indicative` at
# 10%, so the first two arms are unusable and only the third is worth reporting.
# Everything ball-dependent — possession, passes, sequences — collapses with
# that rate, because the ball is only a handful of pixels to begin with.
#
# The two profiles below were then measured end to end over that same clip on an
# M-series Mac (MPS, soccer_yolov8m_v1.pt), which is where their numbers come
# from:
#
#     live (960px,  stride 6)  ->   6.6% ball, 0.88x real time, unusable
#     post (1920px, stride 3)  ->  38.3% ball, 3.11x real time, measured
#
# So the two ends cannot be reconciled in one setting: the size that grades
# measured is three times too slow to follow a live feed, and the size that
# follows a live feed does not clear the 10% floor. Hence two named profiles,
# chosen deliberately by the caller rather than one default that quietly fails
# at both jobs.
#
# Note how little headroom live has — 0.88x real time on a local file with
# nothing else running. It is real time, but not comfortably.
# --------------------------------------------------------------------------- #
LIVE_PROFILE = "live"
POST_PROFILE = "post"
DEFAULT_PROFILE = LIVE_PROFILE

# Bounds for the `post` profile's auto-scaling.
#
# Upper bound. The source's own longest side is the ceiling worth paying for:
# past native there is no extra detail, only upscaling, so the cap only bites on
# footage above 1080p. Inference FLOPs are quadratic in imgsz; measured
# end-to-end it came out softer than that — 1920 cost 1.8x per frame against
# 960, because decode, tracking and team clustering do not scale with inference
# size — but the direction holds and post already runs at 3.1x real time. 4K at
# native on top of that turns a 90-minute match into most of a day. 1920 is also
# the largest size anyone has measured here, and it is already 1.5x the 1280 the
# weights were trained at, so gains above it are speculation while the cost is
# not. Raise this only alongside a measurement that justifies it.
#
# Lower bound. 360p footage analysed at its own 640 would be worse than the live
# profile. Below roughly 960 the ball is too few pixels whatever the source is,
# so small footage is upscaled rather than run at a size that cannot work.
POST_IMGSZ_MAX = 1920
POST_IMGSZ_MIN = 960

# YOLO wants the inference size to be a multiple of the model stride.
# Ultralytics rounds silently; rounding here means the size we report and record
# in run_quality is the size that actually ran.
_IMGSZ_MULTIPLE = 32


@dataclass(frozen=True)
class AnalysisProfile:
    """A named (imgsz, stride) pairing plus what it is honestly good for."""

    name: str
    detection_imgsz: int      # used as-is when the source size is unknown
    frame_stride: int
    scale_to_source: bool     # raise imgsz towards the footage's longest side
    # The best grade this profile can be expected to reach — a ceiling, not a
    # promise. quality.py decides the real one from what the run actually saw,
    # and live in particular can and does land below its ceiling.
    expected_grade: str
    summary: str


PROFILES = {
    LIVE_PROFILE: AnalysisProfile(
        name=LIVE_PROFILE,
        detection_imgsz=960,
        frame_stride=6,
        scale_to_source=False,
        expected_grade="indicative",
        summary="Stays ahead of a live feed. The ball is missed on most frames "
                "at this size, so possession and passing are directional at "
                "best — on the 1080p clip measured here it saw the ball on 6.6% "
                "of frames, below the floor for showing figures at all.",
    ),
    POST_PROFILE: AnalysisProfile(
        name=POST_PROFILE,
        detection_imgsz=POST_IMGSZ_MAX,
        frame_stride=3,
        scale_to_source=True,
        expected_grade="measured",
        summary="Runs at the footage's own resolution once the match is over. "
                "Around three times slower than real time, and the only profile "
                "that has reached a measured grade (38.3% on the same clip).",
    ),
}


def get_profile(name: object = None) -> AnalysisProfile:
    """Look up a profile by name. Empty or None gives the default."""
    key = str(name or DEFAULT_PROFILE).strip().lower()
    if key not in PROFILES:
        raise ValueError(
            f"Unknown analysis profile {name!r}; "
            f"expected one of {sorted(PROFILES)}"
        )
    return PROFILES[key]


def _round_imgsz(value: int) -> int:
    """Round up to the next model-stride multiple, never below one stride."""
    step = _IMGSZ_MULTIPLE
    return max(step, -(-int(value) // step) * step)


def profile_imgsz(profile: AnalysisProfile, source_longest_side: int = 0) -> int:
    """The inference size ``profile`` should use for footage of this size.

    A ``source_longest_side`` of 0 means the capture is not open yet, so there is
    nothing to scale to and the profile's declared size stands.
    """
    longest = int(source_longest_side or 0)
    if not profile.scale_to_source or longest <= 0:
        return _round_imgsz(profile.detection_imgsz)
    return _round_imgsz(min(POST_IMGSZ_MAX, max(POST_IMGSZ_MIN, longest)))


def resolve_profile_settings(name: object = None, source_longest_side: int = 0,
                             imgsz: Optional[int] = None,
                             stride: Optional[int] = None) -> dict:
    """Profile defaults with explicit overrides applied on top.

    The overrides are what keeps existing command lines and saved feed settings
    working: anything passed explicitly wins, anything omitted comes from the
    profile.
    """
    profile = get_profile(name)
    resolved_imgsz = profile_imgsz(profile, source_longest_side)
    auto = profile.scale_to_source and int(source_longest_side or 0) > 0

    if imgsz is not None and int(imgsz) > 0:
        resolved_imgsz, auto = _round_imgsz(int(imgsz)), False
    resolved_stride = profile.frame_stride
    if stride is not None and int(stride) > 0:
        resolved_stride = int(stride)

    return {
        "profile": profile.name,
        "detection_imgsz": resolved_imgsz,
        "frame_stride": max(1, resolved_stride),
        "imgsz_auto": auto,
        "expected_grade": profile.expected_grade,
    }


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
    # Which named profile produced the stride/imgsz above, when one did. Carried
    # into run_quality so a grade can be read months later against the settings
    # that earned it. Empty means the values were set by hand.
    profile: str = ""

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

    def apply_profile(self, name: object = None, source_longest_side: int = 0,
                      imgsz: Optional[int] = None,
                      stride: Optional[int] = None) -> "PipelineConfig":
        """Set stride/imgsz from a named profile, in place. Returns ``self``.

        Callable twice: once before the capture is open (no source size, so the
        profile's declared size stands) and again once the frame dimensions are
        known, which is the only point at which `post` can scale to native.
        """
        chosen = resolve_profile_settings(
            name, source_longest_side=source_longest_side,
            imgsz=imgsz, stride=stride)
        self.profile = chosen["profile"]
        self.detection_imgsz = chosen["detection_imgsz"]
        self.frame_stride = chosen["frame_stride"]
        return self

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
