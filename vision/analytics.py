#!/usr/bin/env python3
"""Kickoff Pulse — spatial analytics over vision tracking output.

Pure, offline, NumPy-only functions that turn a ``match_stats.json`` document
(specifically its per-frame ``spatial_tracking_frames``) into the team/player
spatial metrics: heatmaps, average positions (formation), team-shape metrics,
and territory.

None of these require the ball, so they work today on player tracking alone.
Coordinates are the normalised 0..100 tactical system (x along the pitch length,
y across its width); the numbers are image-space until pitch calibration lands,
then become true tactical coordinates with no change here.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

Point = Tuple[float, float]


# --------------------------------------------------------------------------- #
# Loading / iteration
# --------------------------------------------------------------------------- #
def load_stats(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def frames(stats: dict) -> List[dict]:
    """The per-frame tracking records from a match_stats document."""
    return stats.get("tracking_data", {}).get("spatial_tracking_frames", []) or []


def teams_present(stats: dict) -> List[str]:
    seen = []
    for fr in frames(stats):
        for p in fr.get("players", []):
            t = p.get("team")
            if t and t not in seen:
                seen.append(t)
    return seen


# --------------------------------------------------------------------------- #
# Point collection
# --------------------------------------------------------------------------- #
def collect_player_points(stats: dict) -> Dict[str, dict]:
    """``{player_id: {"team": t, "points": [(x, y), ...]}}`` over all frames."""
    out: Dict[str, dict] = {}
    for fr in frames(stats):
        for p in fr.get("players", []):
            x, y = p.get("x"), p.get("y")
            if x is None or y is None:
                continue
            rec = out.setdefault(p.get("id"), {"team": p.get("team"), "points": []})
            rec["points"].append((float(x), float(y)))
            if rec["team"] is None and p.get("team"):
                rec["team"] = p.get("team")
    return out


def team_points(stats: dict, team: Optional[str] = None) -> np.ndarray:
    """All player positions (``(N, 2)``) for a team (or everyone if None)."""
    pts: List[Point] = []
    for fr in frames(stats):
        for p in fr.get("players", []):
            if team is not None and p.get("team") != team:
                continue
            x, y = p.get("x"), p.get("y")
            if x is None or y is None:
                continue
            pts.append((float(x), float(y)))
    return np.asarray(pts, dtype=float).reshape(-1, 2)


def player_points(stats: dict, player_id: str) -> np.ndarray:
    rec = collect_player_points(stats).get(player_id)
    if not rec:
        return np.zeros((0, 2))
    return np.asarray(rec["points"], dtype=float).reshape(-1, 2)


# --------------------------------------------------------------------------- #
# Heatmap
# --------------------------------------------------------------------------- #
def heatmap(
    points: Sequence[Point],
    bins: Tuple[int, int] = (24, 16),
    rng: Tuple[Tuple[float, float], Tuple[float, float]] = ((0, 100), (0, 100)),
    normalize: bool = True,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """2D occupancy histogram. Returns ``(H, xedges, yedges)``.

    ``H`` has shape ``(bins_x, bins_y)`` (``H[i_x, i_y]``); transpose for image
    display. When ``normalize``, values are scaled to ``[0, 1]`` by the peak.
    """
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(pts) == 0:
        H = np.zeros(bins)
        return (
            H,
            np.linspace(rng[0][0], rng[0][1], bins[0] + 1),
            np.linspace(rng[1][0], rng[1][1], bins[1] + 1),
        )
    H, xedges, yedges = np.histogram2d(
        pts[:, 0], pts[:, 1], bins=bins, range=rng
    )
    if normalize and H.max() > 0:
        H = H / H.max()
    return H, xedges, yedges


# --------------------------------------------------------------------------- #
# Average positions (formation)
# --------------------------------------------------------------------------- #
def average_positions(
    stats: dict, team: Optional[str] = None, min_frames: int = 3
) -> List[dict]:
    """Mean position + spread per tracked player (the 'formation' dots).

    Players seen in fewer than ``min_frames`` frames are dropped as noise.
    """
    out: List[dict] = []
    for pid, rec in collect_player_points(stats).items():
        if team is not None and rec["team"] != team:
            continue
        pts = np.asarray(rec["points"], dtype=float)
        if len(pts) < min_frames:
            continue
        std = pts.std(axis=0)
        out.append(
            {
                "id": pid,
                "team": rec["team"],
                "x": float(pts[:, 0].mean()),
                "y": float(pts[:, 1].mean()),
                "n": int(len(pts)),
                "spread": float(np.hypot(std[0], std[1])),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Team shape
# --------------------------------------------------------------------------- #
def team_shape_series(stats: dict, team: str) -> List[dict]:
    """Per-frame shape metrics for one team (frames with >=2 players)."""
    rows: List[dict] = []
    for fr in frames(stats):
        pts = np.asarray(
            [
                (p["x"], p["y"])
                for p in fr.get("players", [])
                if p.get("team") == team and p.get("x") is not None
            ],
            dtype=float,
        ).reshape(-1, 2)
        if len(pts) < 2:
            continue
        cx, cy = pts.mean(axis=0)
        compactness = float(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy).mean())
        rows.append(
            {
                "frame": fr.get("frame_index"),
                "timestamp": fr.get("timestamp"),
                "n": int(len(pts)),
                "centroid_x": float(cx),
                "centroid_y": float(cy),
                "spread_length": float(pts[:, 0].std()),   # front-to-back
                "spread_width": float(pts[:, 1].std()),     # side-to-side
                "compactness": compactness,
            }
        )
    return rows


def team_shape_summary(stats: dict, team: str) -> Optional[dict]:
    """Match-averaged shape metrics for one team, or ``None`` if no data."""
    rows = team_shape_series(stats, team)
    if not rows:
        return None

    def avg(key: str) -> float:
        return float(np.mean([r[key] for r in rows]))

    return {
        "team": team,
        "frames": len(rows),
        "avg_players": avg("n"),
        "centroid_x": avg("centroid_x"),
        "centroid_y": avg("centroid_y"),
        "spread_length": avg("spread_length"),
        "spread_width": avg("spread_width"),
        "compactness": avg("compactness"),
    }


# --------------------------------------------------------------------------- #
# Territory
# --------------------------------------------------------------------------- #
def territory(stats: dict, home_attacks_positive_x: bool = True) -> Dict[str, dict]:
    """Share of player-presence in each third, attack-relative, per team.

    Returns ``{"Home": {"defensive": f, "middle": f, "attacking": f}, "Away": ...}``
    with fractions summing to 1 per team.
    """
    res = {t: {"defensive": 0.0, "middle": 0.0, "attacking": 0.0} for t in ("Home", "Away")}
    for fr in frames(stats):
        for p in fr.get("players", []):
            t, x = p.get("team"), p.get("x")
            if t not in res or x is None:
                continue
            advancing = home_attacks_positive_x if t == "Home" else not home_attacks_positive_x
            advance = x if advancing else 100.0 - x
            if advance >= 66.667:
                res[t]["attacking"] += 1
            elif advance <= 33.333:
                res[t]["defensive"] += 1
            else:
                res[t]["middle"] += 1
    for t, thirds in res.items():
        total = sum(thirds.values()) or 1.0
        for k in thirds:
            thirds[k] = thirds[k] / total
    return res
