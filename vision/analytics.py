#!/usr/bin/env python3
"""Kickoff Pulse — spatial analytics over vision tracking output.

Pure, offline, NumPy-only functions that turn a ``match_stats.json`` document
(specifically its per-frame ``spatial_tracking_frames``) into the team/player
spatial metrics: heatmaps, average positions (formation), team-shape metrics,
and territory.

None of these require the ball, so they work today on player tracking alone.
Coordinates are the normalised 0..100 tactical system (x along the pitch length,
y across its width); the numbers are image-space until pitch calibration lands,
then become true tactical coordinates with no change here -- except that a
calibrated run can place a point off the pitch entirely, which an uncalibrated
one cannot. See ``usable_xy``.

Two conventions run through the file and are worth keeping straight. Positions
are absolute (x=100 is one particular goal line, whoever is attacking it), while
every *statement* about them -- thirds, wings, "higher line" -- is relative to
the team it describes. ``is_advancing`` and ``attack_relative`` are the only
places that flip between the two; see docs/SPATIAL_VALIDATION.md for the bugs
that came of mixing them by hand.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

Point = Tuple[float, float]

# How far outside the 0..100 box a position may sit and still be believed.
# Generous on purpose: a throw-in taker, a keeper off his line behind the goal
# and a player tracked a step over the touchline are all real positions. What
# this excludes is the other kind of out-of-range value -- see `usable_xy`.
PITCH_MARGIN = 10.0


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
# Direction: which way is a team playing?
#
# Every "attacking / defensive", "high line" or "left wing" statement in this
# file is relative to the team that owns it, so the flip belongs in one place.
# Mixing an attack-relative quantity with an absolute one is the bug that hid in
# `_zone_label` and in the summary's line-height comparison.
# --------------------------------------------------------------------------- #
def is_advancing(team: Optional[str], home_attacks_positive_x: bool = True) -> bool:
    """True if ``team`` attacks towards x=100, false if towards x=0."""
    return home_attacks_positive_x if team == "Home" else not home_attacks_positive_x


def attack_relative(value: float, advancing: bool) -> float:
    """Re-express an absolute 0..100 axis position from the team's own end.

    Works for both axes. On x, 0 becomes the team's own goal line and 100 the
    opponent's. On y, 0 becomes the team's own left touchline -- a team playing
    the other way sees the same touchline on its other hand, which is why the
    flank labels flip alongside the thirds.
    """
    return value if advancing else 100.0 - value


# --------------------------------------------------------------------------- #
# Point collection
# --------------------------------------------------------------------------- #
def usable_xy(player: dict) -> Optional[Point]:
    """A player record's position, or None if it can't be trusted as one.

    One definition of a usable point for every consumer in this file. Before
    this existed `collect_player_points` required both coordinates while
    `team_shape_series` checked only x, so a record carrying x without y raised
    instead of being skipped.

    The range check is inert on an uncalibrated run: those coordinates are pixel
    positions divided by the frame size, so the worst they can do is spill a few
    units past 0 or 100 where a detection box overhangs the frame edge. It
    exists for the calibrated case, where the homography happily projects
    whatever the detector found near or above the horizon -- a face in the
    crowd, someone on the bench -- to a point a hundred pitch-lengths away. One
    of those drags a centroid, a compactness or an average position to nonsense,
    so it is dropped rather than averaged in. NaN fails the comparison too, and
    is dropped for the same reason.
    """
    x, y = player.get("x"), player.get("y")
    if x is None or y is None:
        return None
    x, y = float(x), float(y)
    lo, hi = -PITCH_MARGIN, 100.0 + PITCH_MARGIN
    if not (lo <= x <= hi and lo <= y <= hi):
        return None
    return x, y


def track_teams(stats: dict) -> Dict[str, Optional[str]]:
    """The team each tracked id belongs to, decided once over the whole run.

    A track is one player, so its team is a property of the track rather than of
    any single frame: the colour clusterer reports None until it has fitted, and
    can disagree with itself on a blurred one. `vision/teams.py` already
    majority-votes a track's colour history for exactly that reason; this is the
    same convention applied at the document level, so the heatmap, the formation
    dots and the per-frame shape all agree about who is on which team. Ties go
    to the label seen first.
    """
    votes: Dict[str, Dict[str, int]] = {}
    first_seen: Dict[str, List[str]] = {}
    for fr in frames(stats):
        for p in fr.get("players", []):
            pid, team = p.get("id"), p.get("team")
            tally = votes.setdefault(pid, {})
            order = first_seen.setdefault(pid, [])
            if not team:
                continue
            tally[team] = tally.get(team, 0) + 1
            if team not in order:
                order.append(team)
    out: Dict[str, Optional[str]] = {}
    for pid, tally in votes.items():
        if not tally:
            out[pid] = None
            continue
        best = max(tally.values())
        out[pid] = next(t for t in first_seen[pid] if tally[t] == best)
    return out


def collect_player_points(stats: dict) -> Dict[str, dict]:
    """``{player_id: {"team": t, "points": [(x, y), ...]}}`` over all frames."""
    resolved = track_teams(stats)
    out: Dict[str, dict] = {}
    for fr in frames(stats):
        for p in fr.get("players", []):
            xy = usable_xy(p)
            if xy is None:
                continue
            pid = p.get("id")
            rec = out.setdefault(pid, {"team": resolved.get(pid), "points": []})
            rec["points"].append(xy)
    return out


def team_points(stats: dict, team: Optional[str] = None) -> np.ndarray:
    """All player positions (``(N, 2)``) for a team (or everyone if None).

    Selection is by the track's resolved team, not by the label carried on each
    individual frame, so this and `average_positions` see the same points. They
    did not before: the formation dots counted a track's early unlabelled
    sightings and the heatmap threw them away.
    """
    resolved = track_teams(stats) if team is not None else {}
    pts: List[Point] = []
    for fr in frames(stats):
        for p in fr.get("players", []):
            if team is not None and resolved.get(p.get("id")) != team:
                continue
            xy = usable_xy(p)
            if xy is None:
                continue
            pts.append(xy)
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

    ``spread`` is the RMS distance from the player's own mean position, which is
    not the same statistic as ``team_shape_series``'s ``compactness`` (a mean
    distance, and about the team centroid rather than a player's own). Both are
    "how spread out", so keep the names straight before comparing them.
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
    """Per-frame shape metrics for one team (frames with >=2 players).

    Membership comes from the track's resolved team, so a player counts towards
    his side's shape in the frames before the colour clusterer had pinned him
    down -- otherwise the opening frames report a thinner, tighter block than
    was actually on the pitch.
    """
    resolved = track_teams(stats)
    rows: List[dict] = []
    for fr in frames(stats):
        frame_pts: List[Point] = []
        for p in fr.get("players", []):
            if resolved.get(p.get("id")) != team:
                continue
            xy = usable_xy(p)
            if xy is not None:
                frame_pts.append(xy)
        pts = np.asarray(frame_pts, dtype=float).reshape(-1, 2)
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
    resolved = track_teams(stats)
    for fr in frames(stats):
        for p in fr.get("players", []):
            t = resolved.get(p.get("id"))
            xy = usable_xy(p)
            if t not in res or xy is None:
                continue
            advance = attack_relative(xy[0], is_advancing(t, home_attacks_positive_x))
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


# --------------------------------------------------------------------------- #
# Natural-language digest (context for the AI analyst)
# --------------------------------------------------------------------------- #
def _zone_label(cx_idx: int, cy_idx: int, advancing: bool) -> str:
    thirds = (["defensive", "middle", "attacking"] if advancing
              else ["attacking", "middle", "defensive"])
    # Flank flips with direction for the same reason the thirds do: a team
    # attacking the other way sees the same touchline on its other hand. Left
    # here always means the team's own left, never a fixed side of the frame.
    # (Bird's eye with y increasing down the page: face x=100 and your left hand
    # points at y=0, so index 0 is "left" for a team attacking towards x=100.)
    lateral = (["left", "central", "right"] if advancing
               else ["right", "central", "left"])
    return f"{thirds[cx_idx]} third / {lateral[cy_idx]}"


def hotspot_zone(points: Sequence[Point], advancing: bool) -> Optional[str]:
    """Coarsest (3x3) busiest zone label for a set of positions."""
    H, _xe, _ye = heatmap(points, bins=(3, 3), normalize=False)
    if H.sum() == 0:
        return None
    ix, iy = np.unravel_index(int(np.argmax(H)), H.shape)
    return _zone_label(int(ix), int(iy), advancing)


def spatial_summary(stats: dict, home_attacks_positive_x: bool = True) -> str:
    """A compact, model-friendly digest of the spatial findings.

    This is the context handed to the local AI analyst so it can answer
    positioning / shape / territory questions from real computed numbers.
    """
    lines: List[str] = []
    space = stats.get("tracking_data", {}).get("coordinate_space", "image")
    n_frames = len(frames(stats))
    teams = teams_present(stats)
    n_players = len(collect_player_points(stats))

    lines.append(
        f"Vision spatial findings: {n_frames} sampled frames, "
        f"{n_players} tracked player-ids, teams {', '.join(teams) or 'unlabelled'}."
    )
    if space != "pitch":
        lines.append(
            "NOTE: coordinates are UNCALIBRATED image space — team separation "
            "and left/right are meaningful, but pitch depth (defensive vs "
            "attacking) and absolute distances are approximate."
        )

    terr = territory(stats, home_attacks_positive_x)
    for team in teams:
        summ = team_shape_summary(stats, team)
        if not summ:
            continue
        advancing = is_advancing(team, home_attacks_positive_x)
        zone = hotspot_zone(team_points(stats, team), advancing)
        t = terr.get(team, {})
        # Report the centroid attack-relative like everything else on this line.
        # Printed as raw x/y it was the one absolute number among team-relative
        # ones, so the model had no way to reconcile "centroid 30" with
        # "attacking third 70%" for the side playing towards x=0.
        line_x = attack_relative(summ["centroid_x"], advancing)
        line_y = attack_relative(summ["centroid_y"], advancing)
        lines.append(
            f"{team}: ~{summ['avg_players']:.0f} players/frame; "
            f"compactness {summ['compactness']:.1f} (lower = tighter block); "
            f"depth {summ['spread_length']:.1f}, width {summ['spread_width']:.1f}; "
            f"avg position {line_x:.0f} up-pitch / {line_y:.0f} across "
            f"(0 = own goal line, 0 = own left touchline); "
            f"territory def {t.get('defensive', 0)*100:.0f}% / "
            f"mid {t.get('middle', 0)*100:.0f}% / "
            f"att {t.get('attacking', 0)*100:.0f}%; "
            f"busiest area: {zone or 'n/a'}."
        )

    if len(teams) == 2:
        sa = team_shape_summary(stats, teams[0])
        sb = team_shape_summary(stats, teams[1])
        if sa and sb:
            tighter = teams[0] if sa["compactness"] <= sb["compactness"] else teams[1]
            # A high line means far from your OWN goal, so the two centroids
            # cannot be compared as raw x. The sides attack opposite ways, so
            # for one of them a large x is the deepest position on the pitch,
            # and comparing the absolute numbers named the wrong team whenever
            # the deeper side happened to be the one attacking towards x=0.
            adv_a = attack_relative(
                sa["centroid_x"], is_advancing(teams[0], home_attacks_positive_x))
            adv_b = attack_relative(
                sb["centroid_x"], is_advancing(teams[1], home_attacks_positive_x))
            higher = teams[0] if adv_a >= adv_b else teams[1]
            lines.append(
                f"Comparison: {tighter} held the more compact shape; "
                f"{higher} had the higher average line."
            )
    return "\n".join(lines)
