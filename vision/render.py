#!/usr/bin/env python3
"""Kickoff Pulse — vision drawing helpers.

Every picture the vision stack produces: annotated camera frames, the top-down
tactical map with its overlay layers, and the static passing map.

These used to live inside the Video Analysis page, which meant the persistent
live runner kept its own near-copy of ``annotate`` — the two drifted apart, so
the Live Eye frame and the in-app preview did not look the same. They are shared
from here now.

Pure OpenCV/NumPy: no Streamlit, so the headless runner can import it.
"""

from __future__ import annotations

import cv2
import numpy as np

import icons as IC


def _hex_to_bgr(hex_color: str):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)


HOME_BGR = _hex_to_bgr(IC.HOME_COLOR)
AWAY_BGR = _hex_to_bgr(IC.AWAY_COLOR)

# Five-lane (half-space) split, as fractions of pitch width across the play
# axis. Boundaries align with the penalty-box width so the lanes read like a
# real pitch: wide / half-space / centre / half-space / wide.
_LANE_BOUNDS = [0.0, 0.21, 0.37, 0.63, 0.79, 1.0]
_LANE_LABELS = ["WIDE", "HALF-SPACE", "CENTRE", "HALF-SPACE", "WIDE"]
# Centre darkest, half-spaces mid, wide unshaded (matches the reference art).
_LANE_SHADE = [0.0, 0.18, 0.30, 0.18, 0.0]
_LAYER_COL = (235, 235, 235)
_BALL_COL = (0, 215, 255)        # BGR amber
_OPEN_COL = (90, 220, 90)        # open passing lane
_BLOCK_COL = (80, 80, 90)        # covered passing lane

# Every layer key the tactical map understands, in human order (drives the UI).
LAYER_KEYS = ["zones", "half_spaces", "thirds", "team_shape", "avg_position",
              "space_control", "passing_lanes", "ball_trail"]


# --------------------------------------------------------------------------- #
# Camera frame
# --------------------------------------------------------------------------- #
def annotate(frame, detections):
    """Draw detection boxes (player / ball / referee) on the camera frame."""
    img = frame.copy()
    for d in detections:
        x1, y1, x2, y2 = (int(v) for v in d.box)
        if d.cls_name == "ball":
            col, lab, th = (0, 255, 255), f"BALL {d.confidence:.2f}", 3
        elif d.cls_name == "referee":
            col, lab, th = (0, 140, 255), "REF", 2
        else:
            col, lab, th = (0, 230, 0), f"P{d.track_id}", 2
        cv2.rectangle(img, (x1, y1), (x2, y2), col, th)
        cv2.putText(img, lab, (x1, max(0, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
    return img


def annotate_with_clock(frame, detections, record):
    """An annotated frame stamped with the match time and ball status.

    This is what the live runner writes for the Live Eye page.
    """
    img = annotate(frame, detections)
    cv2.putText(img, f"{record.timestamp}   ball:{record.ball.status}",
                (14, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 120), 2,
                cv2.LINE_AA)
    return img


# --------------------------------------------------------------------------- #
# Pitch geometry
# --------------------------------------------------------------------------- #
def _px(x, y, w, h):
    """Normalised 0..100 pitch coords -> integer pixel coords."""
    return int(x / 100 * w), int(y / 100 * h)


def _team_points(players, team):
    return [(p.x, p.y) for p in players if p.team == team]


def _base_pitch(w, h):
    """Green field with halfway line, centre circle and penalty boxes."""
    pitch = np.full((h, w, 3), (40, 110, 40), dtype=np.uint8)
    cv2.rectangle(pitch, (6, 6), (w - 6, h - 6), (255, 255, 255), 2)
    cv2.line(pitch, (w // 2, 6), (w // 2, h - 6), (255, 255, 255), 1)
    cv2.circle(pitch, (w // 2, h // 2), 46, (255, 255, 255), 1)
    by0, by1 = int(0.21 * h), int(0.79 * h)
    cv2.rectangle(pitch, (6, by0), (int(0.16 * w), by1), (255, 255, 255), 1)
    cv2.rectangle(pitch, (int(0.84 * w), by0), (w - 6, by1), (255, 255, 255), 1)
    return pitch


# --------------------------------------------------------------------------- #
# Tactical overlay layers
# --------------------------------------------------------------------------- #
def _draw_half_spaces(pitch, w, h):
    """Five lanes along the play axis: wide / half-space / centre."""
    for i in range(5):
        y0 = int(_LANE_BOUNDS[i] * h)
        y1 = int(_LANE_BOUNDS[i + 1] * h)
        shade = _LANE_SHADE[i]
        if shade > 0:
            overlay = pitch.copy()
            cv2.rectangle(overlay, (6, y0), (w - 6, y1), (0, 0, 0), -1)
            cv2.addWeighted(overlay, shade, pitch, 1 - shade, 0, pitch)
        if i > 0:  # lane divider
            cv2.line(pitch, (6, y0), (w - 6, y0), _LAYER_COL, 1, cv2.LINE_AA)
        ty = (y0 + y1) // 2 + 4
        cv2.putText(pitch, _LANE_LABELS[i], (12, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, _LAYER_COL, 1, cv2.LINE_AA)


def _draw_zones(pitch, w, h):
    """6x3 tactical grid, zones numbered 1-18 (column-major, top->bottom)."""
    for c in range(1, 6):
        x = int(c / 6 * w)
        cv2.line(pitch, (x, 6), (x, h - 6), _LAYER_COL, 1, cv2.LINE_AA)
    for r in range(1, 3):
        y = int(r / 3 * h)
        cv2.line(pitch, (6, y), (w - 6, y), _LAYER_COL, 1, cv2.LINE_AA)
    for c in range(6):
        for r in range(3):
            text = str(c * 3 + r + 1)
            cx = int((c + 0.5) / 6 * w)
            cy = int((r + 0.5) / 3 * h)
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.putText(pitch, text, (cx - tw // 2, cy + th // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, _LAYER_COL, 1, cv2.LINE_AA)


def _draw_thirds(pitch, w, h):
    """Defensive / middle / attacking thirds along the direction of play."""
    for frac in (1 / 3, 2 / 3):
        x = int(frac * w)
        cv2.line(pitch, (x, 6), (x, h - 6), _LAYER_COL, 1, cv2.LINE_AA)
    for i, lab in enumerate(("DEF", "MID", "ATT")):
        cx = int((i + 0.5) / 3 * w)
        (tw, _th), _ = cv2.getTextSize(lab, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.putText(pitch, lab, (cx - tw // 2, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, _LAYER_COL, 1, cv2.LINE_AA)


def _draw_team_shape(pitch, players, w, h):
    """Convex hull of each team — the space the side is occupying."""
    for team, col in (("Home", HOME_BGR), ("Away", AWAY_BGR)):
        pts = [_px(x, y, w, h) for x, y in _team_points(players, team)]
        if len(pts) < 3:
            continue
        hull = cv2.convexHull(np.array(pts, dtype=np.int32))
        overlay = pitch.copy()
        cv2.fillConvexPoly(overlay, hull, col)
        cv2.addWeighted(overlay, 0.16, pitch, 0.84, 0, pitch)
        cv2.polylines(pitch, [hull], True, col, 1, cv2.LINE_AA)


def _draw_avg_position(pitch, players, w, h):
    """Each team's centroid plus its rearmost and foremost player lines."""
    for team, col in (("Home", HOME_BGR), ("Away", AWAY_BGR)):
        pts = _team_points(players, team)
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        for xx in (min(xs), max(xs)):       # rear / front line of the block
            lx = int(xx / 100 * w)
            cv2.line(pitch, (lx, 6), (lx, h - 6), col, 1, cv2.LINE_AA)
        cx, cy = _px(sum(xs) / len(xs), sum(ys) / len(ys), w, h)
        cv2.circle(pitch, (cx, cy), 11, col, 2)
        cv2.drawMarker(pitch, (cx, cy), col, cv2.MARKER_CROSS, 14, 2)


def _draw_space_control(pitch, players, w, h):
    """Voronoi-style space control: tint each region by its nearest team."""
    pl = [(p.x, p.y, p.team) for p in players if p.team in ("Home", "Away")]
    if len(pl) < 2:
        return
    P = np.array([[x, y] for x, y, _ in pl], dtype=np.float32)
    cols = np.array([HOME_BGR if t == "Home" else AWAY_BGR for _, _, t in pl],
                    dtype=np.uint8)
    gw, gh = 80, 52
    gx = np.linspace(0, 100, gw, dtype=np.float32)
    gy = np.linspace(0, 100, gh, dtype=np.float32)
    grid_x, grid_y = np.meshgrid(gx, gy)
    cells = np.stack([grid_x.ravel(), grid_y.ravel()], axis=1)
    diff = cells[:, None, :] - P[None, :, :]
    idx = (diff * diff).sum(axis=2).argmin(axis=1)
    small = cols[idx].reshape(gh, gw, 3)
    big = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    blended = cv2.addWeighted(big, 0.22, pitch, 0.78, 0)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.rectangle(mask, (6, 6), (w - 6, h - 6), 255, -1)
    pitch[mask == 255] = blended[mask == 255]


def _seg_distance(px, py, ax, ay, bx, by):
    """Distance from point P to segment AB (in pitch units)."""
    abx, aby = bx - ax, by - ay
    denom = abx * abx + aby * aby + 1e-9
    t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / denom))
    cx, cy = ax + t * abx, ay + t * aby
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _draw_passing_lanes(pitch, record, w, h, block_thresh=5.0):
    """From the likely ball carrier, draw lanes to team-mates (open vs covered)."""
    if record.ball.x is None:
        return
    bx, by = record.ball.x, record.ball.y
    teamed = [p for p in record.players if p.team in ("Home", "Away")]
    if not teamed:
        return
    carrier = min(teamed, key=lambda p: (p.x - bx) ** 2 + (p.y - by) ** 2)
    opps = [p for p in teamed if p.team != carrier.team]
    cpt = _px(carrier.x, carrier.y, w, h)
    for m in teamed:
        if m.team != carrier.team or m is carrier:
            continue
        blocked = any(_seg_distance(o.x, o.y, carrier.x, carrier.y, m.x, m.y)
                      < block_thresh for o in opps)
        cv2.line(pitch, cpt, _px(m.x, m.y, w, h),
                 _BLOCK_COL if blocked else _OPEN_COL, 1, cv2.LINE_AA)
    cv2.circle(pitch, cpt, 9, _BALL_COL, 2)


def _draw_ball_trail(pitch, trail, w, h):
    """Fading polyline of the ball's recent path."""
    pts = [_px(x, y, w, h) for x, y in trail if x is not None]
    n = len(pts)
    for i in range(1, n):
        a = i / n                      # newer segments brighter / thicker
        col = (int(_BALL_COL[0] * a), int(_BALL_COL[1] * a), int(_BALL_COL[2] * a))
        cv2.line(pitch, pts[i - 1], pts[i], col, 1 + int(2 * a), cv2.LINE_AA)


# --------------------------------------------------------------------------- #
# Maps
# --------------------------------------------------------------------------- #
def tactical_map(record, w=520, h=340, layers=None, ball_trail=None):
    """Top-down pitch with player dots (by team) + ball, from normalised coords.

    ``layers`` is a dict of ``LAYER_KEYS`` -> bool toggling tactical overlays;
    ``ball_trail`` is the recent ball path for the trail layer.
    """
    layers = layers or {}
    pitch = _base_pitch(w, h)
    # Fills first (under the grid lines), then grids, then per-team shapes.
    if layers.get("space_control"):
        _draw_space_control(pitch, record.players, w, h)
    if layers.get("half_spaces"):
        _draw_half_spaces(pitch, w, h)
    if layers.get("thirds"):
        _draw_thirds(pitch, w, h)
    if layers.get("zones"):
        _draw_zones(pitch, w, h)
    if layers.get("team_shape"):
        _draw_team_shape(pitch, record.players, w, h)
    if layers.get("avg_position"):
        _draw_avg_position(pitch, record.players, w, h)
    if layers.get("passing_lanes"):
        _draw_passing_lanes(pitch, record, w, h)
    if layers.get("ball_trail") and ball_trail:
        _draw_ball_trail(pitch, ball_trail, w, h)
    # Player dots and ball always render on top.
    for p in record.players:
        cx, cy = _px(p.x, p.y, w, h)
        col = (HOME_BGR if p.team == "Home"
               else AWAY_BGR if p.team == "Away" else (150, 150, 150))
        cv2.circle(pitch, (cx, cy), 6, col, -1)
        cv2.circle(pitch, (cx, cy), 6, (255, 255, 255), 1)
    if record.ball.x is not None:
        bx, by = _px(record.ball.x, record.ball.y, w, h)
        cv2.circle(pitch, (bx, by), 5, (255, 255, 255), -1)
        cv2.circle(pitch, (bx, by), 7, _BALL_COL, 2)
    return pitch


def passing_map(passes, passer=None, w=520, h=340):
    """Static pitch of completed/failed passes as arrows; optional per-passer."""
    pitch = _base_pitch(w, h)
    drawn = 0
    for d in passes:
        if passer and d.get("passer") != passer:
            continue
        sx, sy = d.get("start_coords", [None, None])
        ex, ey = d.get("end_coords", [None, None])
        if None in (sx, sy, ex, ey):
            continue
        col = _OPEN_COL if d.get("outcome") == "completed" else (70, 70, 235)
        a, b = _px(sx, sy, w, h), _px(ex, ey, w, h)
        cv2.arrowedLine(pitch, a, b, col, 2, cv2.LINE_AA, tipLength=0.18)
        cv2.circle(pitch, a, 3, col, -1)
        drawn += 1
    if drawn == 0:
        cv2.putText(pitch, "No passes", (w // 2 - 50, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, _LAYER_COL, 1, cv2.LINE_AA)
    return pitch
