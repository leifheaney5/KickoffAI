#!/usr/bin/env python3
"""Kickoff Pulse — match analysis pipeline (the orchestrator).

Wires every module together into one streaming pass over a match video:

    decode -> detect+track -> identity permanence -> homography
           -> team / jersey -> heuristics -> per-frame record -> match_stats.json

The pipeline owns no analytics logic of its own; it is glue that feeds the
specialised modules in the right order and assembles their results into the
:class:`~vision.schema.MatchStats` document.
"""

from __future__ import annotations

from collections import Counter
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .config import BALL, JERSEY, PLAYER, REFEREE, PipelineConfig
from .detection import (
    Detection,
    Detector,
    bbox_area,
    bbox_center,
    bbox_contains,
    bbox_foot,
    split_by_class,
)
from .heuristics import BallObs, PlayerObs, StatsEngine
from .homography import PitchHomography, fallback_normalised
from .schema import (
    BallState,
    FrameRecord,
    MatchStats,
    PlayerState,
    format_timestamp,
    player_token,
)
from .teams import JerseyOCR, TeamClassifier, torso_patch

FrameCallback = Callable[[FrameRecord], None]


class JerseyBinder:
    """Permanently binds a jersey number to a canonical track id by vote."""

    def __init__(self, lock_votes: int = 3, lock_conf: float = 0.85) -> None:
        self._votes: Dict[int, Counter] = {}
        self._locked: Dict[int, int] = {}
        self.lock_votes = lock_votes
        self.lock_conf = lock_conf

    def is_locked(self, cid: int) -> bool:
        return cid in self._locked

    def add(self, cid: int, number: int, conf: float) -> None:
        if cid in self._locked:
            return
        # A single very confident read, or a quorum of agreeing reads, locks in.
        if conf >= self.lock_conf:
            self._locked[cid] = number
            return
        votes = self._votes.setdefault(cid, Counter())
        votes[number] += 1
        number_, count = votes.most_common(1)[0]
        if count >= self.lock_votes:
            self._locked[cid] = number_

    def number_for(self, cid: int) -> Optional[int]:
        if cid in self._locked:
            return self._locked[cid]
        votes = self._votes.get(cid)
        if votes:
            return votes.most_common(1)[0][0]
        return None


class MatchAnalyzer:
    """End-to-end soccer video analyzer producing ``match_stats.json``."""

    def __init__(
        self,
        config: Optional[PipelineConfig] = None,
        homography: Optional[PitchHomography] = None,
        on_frame: Optional[FrameCallback] = None,
        on_detections: Optional[
            Callable[[int, "np.ndarray", List[Detection], FrameRecord], None]
        ] = None,
        pitch_detector=None,
    ) -> None:
        self.config = config or PipelineConfig()
        self.homography = homography
        self.on_frame = on_frame
        # Optional per-frame pitch homography (handles panning/zooming cameras).
        # When set, it overrides `homography` each frame it succeeds; otherwise
        # the last good homography is kept.
        self.pitch_detector = pitch_detector
        # Optional low-level hook: receives the raw frame + detections + record
        # for each processed frame (useful for overlays / annotated exports).
        self.on_detections = on_detections

        # Detection backend: local Ultralytics by default, or a Roboflow model
        # (paired with ByteTrack) when config.roboflow_model is set.
        if self.config.roboflow_model:
            from .roboflow_backend import RoboflowDetector

            self.detector = RoboflowDetector(self.config)
        else:
            self.detector = Detector(self.config)
        self.identities = None  # built in run() once gate/window are known
        self.teams = TeamClassifier(self.config)
        self.ocr = JerseyOCR(self.config) if self.config.ocr_enabled else None
        self.binder = JerseyBinder()
        self.engine = StatsEngine(self.config)

    # ------------------------------------------------------------------ #
    def run(self, video_path: str) -> MatchStats:
        """Process ``video_path`` end to end and return the stats document."""
        import cv2

        from .tracking import IdentityManager

        self.identities = IdentityManager(
            gate=self.config.reid_gate_norm,
            max_lost_frames=self.config.reid_max_lost_frames,
        )

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise FileNotFoundError(f"Could not open video: {video_path}")

        source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
        self._frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080

        frames: List[FrameRecord] = []
        raw_index = -1
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                raw_index += 1
                if raw_index % self.config.frame_stride != 0:
                    continue

                t_sec = raw_index / source_fps
                if self.config.max_seconds and t_sec > self.config.max_seconds:
                    break

                record = self._process_frame(raw_index, t_sec, frame)

                cap_reached = (
                    self.config.max_frames_recorded
                    and len(frames) >= self.config.max_frames_recorded
                )
                if not cap_reached:
                    frames.append(record)
                if self.on_frame is not None:
                    self.on_frame(record)
                if self.config.show:
                    self._draw(cv2, frame, record)
        finally:
            cap.release()
            if self.config.show:
                cv2.destroyAllWindows()

        stats = MatchStats(
            frame_rate_sampled=self.config.sampled_fps_label(source_fps),
            frames=frames,
            passes=self.engine.events,
            possession=self.engine.possession_summary(),
            # If a homography was ever applied, coordinates are true pitch space.
            coordinate_space="pitch" if self.homography is not None else "image",
        )
        stats.save(self.config.output_path)
        return stats

    # ------------------------------------------------------------------ #
    def _process_frame(
        self, frame_index: int, t_sec: float, frame: np.ndarray
    ) -> FrameRecord:
        # Per-frame pitch homography (panning cameras). Keep the last good one
        # for frames where the pitch model can't see enough landmarks.
        if self.pitch_detector is not None:
            dynamic = self.pitch_detector.homography(frame)
            if dynamic is not None:
                self.homography = dynamic

        detections = self.detector.track(frame)
        grouped = split_by_class(detections)
        players = [d for d in grouped.get(PLAYER, []) if d.track_id is not None]
        balls = grouped.get(BALL, [])
        jerseys = grouped.get(JERSEY, [])

        # 1) Identity permanence — resolve raw track ids to canonical ids using
        #    normalised pitch positions (robust to camera panning).
        foot_px = [bbox_foot(d.box) for d in players]
        player_m, player_norm = self._project(foot_px)
        observations = [
            (d.track_id, tuple(player_norm[i])) for i, d in enumerate(players)
        ]
        remap = self.identities.update(frame_index, observations)

        # 2) Team colour + jersey number per player.
        self._read_jerseys(frame, players, jerseys, remap)
        player_states: List[PlayerState] = []
        player_obs: List[PlayerObs] = []
        for i, det in enumerate(players):
            cid = remap[det.track_id]
            crop = torso_patch(frame, det.box)
            if crop is not None:
                self.teams.observe(cid, crop)
            team = self.teams.team_for(cid)
            jersey = self.binder.number_for(cid)
            token = player_token(team, jersey, cid)
            xy_norm = (float(player_norm[i][0]), float(player_norm[i][1]))
            xy_m = (float(player_m[i][0]), float(player_m[i][1]))
            player_states.append(
                PlayerState(token, jersey, team, xy_norm[0], xy_norm[1])
            )
            player_obs.append(PlayerObs(token, team, xy_m, xy_norm))

        # 3) Ball — highest-confidence detection wins.
        ball_obs = self._resolve_ball(balls)

        # 4) Heuristics — possession + passing; returns the ball status string.
        status = self.engine.update(frame_index, t_sec, ball_obs, player_obs)

        ball_state = (
            BallState(ball_obs.xy_norm[0], ball_obs.xy_norm[1], status)
            if ball_obs is not None
            else BallState(None, None, status)
        )
        record = FrameRecord(
            timestamp=format_timestamp(t_sec),
            frame_index=frame_index,
            ball=ball_state,
            players=player_states,
        )
        if self.on_detections is not None:
            self.on_detections(frame_index, frame, detections, record)
        return record

    # ------------------------------------------------------------------ #
    def _resolve_ball(self, balls: Sequence[Detection]) -> Optional[BallObs]:
        if not balls:
            return None
        ball = max(balls, key=lambda d: d.confidence)
        ball_m, ball_norm = self._project([bbox_center(ball.box)])
        return BallObs(
            xy_m=(float(ball_m[0][0]), float(ball_m[0][1])),
            xy_norm=(float(ball_norm[0][0]), float(ball_norm[0][1])),
        )

    def _read_jerseys(
        self,
        frame: np.ndarray,
        players: Sequence[Detection],
        jerseys: Sequence[Detection],
        remap: Dict[int, int],
    ) -> None:
        """OCR each jersey-number box and bind it to the enclosing player."""
        if self.ocr is None or not jerseys:
            return
        for jersey in jerseys:
            # The player whose box most tightly contains the number wins.
            host = None
            host_area = float("inf")
            for det in players:
                if bbox_contains(det.box, jersey.box) and det.area < host_area:
                    host = det
                    host_area = det.area
            if host is None:
                continue
            cid = remap[host.track_id]
            if self.binder.is_locked(cid):
                continue
            x1, y1, x2, y2 = (int(v) for v in jersey.box)
            crop = frame[max(0, y1) : y2, max(0, x1) : x2]
            read = self.ocr.read_number(crop)
            if read is not None:
                number, conf = read
                self.binder.add(cid, number, conf)

    # ------------------------------------------------------------------ #
    def _project(
        self, points_px: Sequence[Tuple[float, float]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Project pixel points to (metres, normalised-0..100) arrays."""
        if not points_px:
            empty = np.zeros((0, 2), dtype=np.float32)
            return empty, empty
        if self.homography is not None:
            metres = self.homography.to_metres(points_px)
            norm = self.homography.metres_to_normalised(metres)
        else:
            # No calibration: fall back to image-space normalisation and derive
            # an approximate metric plane from it (perspective NOT corrected).
            norm = fallback_normalised(points_px, self._frame_w, self._frame_h)
            metres = np.column_stack(
                [
                    norm[:, 0] / 100.0 * self.config.pitch_length_m,
                    norm[:, 1] / 100.0 * self.config.pitch_width_m,
                ]
            )
        return np.asarray(metres, dtype=np.float32), np.asarray(norm, dtype=np.float32)

    # ------------------------------------------------------------------ #
    def _draw(self, cv2, frame: np.ndarray, record: FrameRecord) -> None:  # pragma: no cover
        """Optional debug overlay (enabled with ``config.show``)."""
        colours = {"Home": (0, 200, 255), "Away": (255, 120, 0), None: (180, 180, 180)}
        for p in record.players:
            x = int(p.x / 100.0 * frame.shape[1])
            y = int(p.y / 100.0 * frame.shape[0])
            cv2.circle(frame, (x, y), 5, colours.get(p.team, (180, 180, 180)), -1)
            cv2.putText(
                frame, p.id, (x + 6, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA,
            )
        cv2.putText(
            frame, f"{record.timestamp}  {record.ball.status}", (12, 28),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 120), 2, cv2.LINE_AA,
        )
        cv2.imshow("Kickoff Pulse — vision", frame)
        cv2.waitKey(1)


def analyze(
    video_path: str,
    config: Optional[PipelineConfig] = None,
    homography: Optional[PitchHomography] = None,
    on_frame: Optional[FrameCallback] = None,
) -> MatchStats:
    """Convenience one-shot: build a :class:`MatchAnalyzer` and run it."""
    return MatchAnalyzer(config, homography, on_frame).run(video_path)
