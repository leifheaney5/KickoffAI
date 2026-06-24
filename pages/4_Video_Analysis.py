#!/usr/bin/env python3
"""
Kickoff Pulse — Video Analysis page (the Eye, live).

Runs the local computer-vision pipeline on a match video and streams the result
into the UI in real time: an annotated camera frame, a top-down tactical map
built from the pitch homography, and live possession / passing stats. Optionally
feeds detected passes straight into the dashboard's event log so the rest of the
app (timeline, stats) reflects them too.
"""

import os
import sys
from collections import deque

import numpy as np
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brand           # noqa: E402
import control         # noqa: E402
import icons as IC     # noqa: E402
import screen_recorder  # noqa: E402

st.set_page_config(page_title=f"{brand.NAME} — Video Analysis",
                   page_icon=brand.LOGO_TRANSPARENT, layout="wide")
st.markdown(brand.global_css(), unsafe_allow_html=True)

# Heavy vision deps are optional; fail gracefully with install guidance.
try:
    import cv2
    from vision import MatchAnalyzer, PipelineConfig
    from vision import bridge as vbridge
    from vision.pitch import DEFAULT_PITCH_MODEL, PitchDetector
    VISION_OK, VISION_ERR = True, ""
except Exception as exc:  # pragma: no cover - import guard
    VISION_OK, VISION_ERR = False, str(exc)

def best_device() -> str:
    """Return the best available torch device: cuda > mps > cpu."""
    try:
        import torch
        if torch.cuda.is_available():
            return "0"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


state = control.load_control()
match_name = (state.get("match_name") or "").strip()
st.markdown(brand.page_header("VISION", match_name or "Video Analysis"),
            unsafe_allow_html=True)

if not VISION_OK:
    st.error("Vision dependencies are not installed.")
    st.code("pip install -r vision/requirements.txt", language="bash")
    st.caption(f"Import error: {VISION_ERR}")
    st.stop()


# --------------------------------------------------------------------------- #
# Drawing helpers
# --------------------------------------------------------------------------- #
def _hex_to_bgr(hex_color: str):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)


HOME_BGR = _hex_to_bgr(IC.HOME_COLOR)
AWAY_BGR = _hex_to_bgr(IC.AWAY_COLOR)


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
        col = HOME_BGR if p.team == "Home" else AWAY_BGR if p.team == "Away" else (150, 150, 150)
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


# --------------------------------------------------------------------------- #
# Live-run helpers (shared by the recorded-video and webcam paths)
# --------------------------------------------------------------------------- #
def list_cameras():
    """Connected camera devices, excluding the screen-capture pseudo-device."""
    try:
        return screen_recorder.list_cameras()
    except Exception:
        return []


def make_placeholders():
    """Create the live view placeholders: camera, tactical map, metrics, feed."""
    v_col, t_col = st.columns(2)
    p = st.columns(5)
    return {
        "frame": v_col.empty(), "map": t_col.empty(),
        "proc": p[0].empty(), "players": p[1].empty(), "ball": p[2].empty(),
        "poss": p[3].empty(), "pass": p[4].empty(), "feed": st.empty(),
    }


def render_live(ph, analyzer, counters, frame, dets, record, map_layers, trail):
    """Update the live placeholders from one processed frame."""
    counters["proc"] += 1
    n_players = sum(1 for d in dets if d.cls_name == "player")
    counters["ball"] += 1 if any(d.cls_name == "ball" for d in dets) else 0
    if record.ball.x is not None:
        trail.append((record.ball.x, record.ball.y))
    ph["frame"].image(annotate(frame, dets), channels="BGR",
                      use_container_width=True,
                      caption=f"Camera · {record.timestamp}")
    ph["map"].image(tactical_map(record, layers=map_layers, ball_trail=list(trail)),
                    channels="BGR", use_container_width=True, caption="Tactical map")
    poss = analyzer.engine.possession_summary()
    events = analyzer.engine.events
    ball_pct = 100 * counters["ball"] / max(1, counters["proc"])
    ph["proc"].metric("Frames", counters["proc"])
    ph["players"].metric("Players", n_players)
    ph["ball"].metric("Ball seen", f"{ball_pct:.0f}%")
    ph["poss"].metric("Possession H/A",
                      f"{poss.team_home_percentage:.0f}/{poss.team_away_percentage:.0f}")
    ph["pass"].metric("Passes", len(events))
    if events:
        lines = []
        for e in events[-5:][::-1]:
            d = e.to_dict()
            lines.append(
                f"`{d['timestamp']}` **{d['passer']}** → "
                f"{d['intended_receiver'] or '—'} · {d['pass_type'].replace('_',' ')} "
                f"· _{d['outcome']}_")
        ph["feed"].markdown("**Recent passes**\n\n" + "\n\n".join(lines))


# --------------------------------------------------------------------------- #
# Controls
# --------------------------------------------------------------------------- #
st.markdown("#### Source & model")
source_kind = st.radio(
    "Source", ["Video file", "Webcam (live)"], horizontal=True,
    help="Analyse a recorded video, or run detection live off a connected camera.")

c1, c2 = st.columns([2, 1])
with c1:
    if source_kind == "Video file":
        default_video = "soccer_test.mp4" if os.path.exists("soccer_test.mp4") else ""
        seed = st.session_state.get("kp_va_video_path", default_video)
        video_path = st.text_input("Video file path", value=seed,
                                   placeholder="path/to/match.mp4")
        cam_index = None
    else:
        cams = list_cameras()
        if cams:
            labels = {i: f"[{i}] {n}" for i, n in cams}
            cam_index = st.selectbox(
                "Camera", [i for i, _ in cams], format_func=lambda i: labels[i],
                help="Connected webcam / capture device. For pitch analytics, "
                     "mount it high and wide so the pitch lines are visible.")
        else:
            cam_index = st.number_input(
                "Camera index", min_value=0, max_value=10, value=0, step=1,
                help="Could not auto-list cameras; enter the device index "
                     "(0 is usually the built-in camera).")
        video_path = None
with c2:
    backend = st.radio("Detection backend", ["Roboflow (cloud)", "Local YOLO"],
                       horizontal=False)

# Path A: record a match from a webcam to a file, then analyse that file. Live
# analysis (Path B) is the "Webcam (live)" source above; this is the fallback —
# capture now, analyse later, and re-run as many times as you like.
if source_kind == "Video file" and screen_recorder.is_supported():
    with st.expander("Record a match from your webcam (then analyse the file)"):
        rec = screen_recorder.status()
        rec_live = rec["recording"] and rec.get("kind") == "webcam"
        cams = list_cameras()
        cam_names = dict(cams)
        if cams:
            rec_cam = st.selectbox(
                "Webcam", [i for i, _ in cams],
                format_func=lambda i: f"[{i}] {cam_names.get(i, '')}",
                disabled=rec["recording"], key="kp_va_rec_cam")
        else:
            rec_cam = st.number_input("Camera index", 0, 10, 0, 1,
                                      disabled=rec["recording"], key="kp_va_rec_cam")
        b1, b2 = st.columns(2)
        if b1.button("●  Record webcam", type="primary",
                     disabled=rec["recording"], use_container_width=True):
            res = screen_recorder.start(label=match_name, source=int(rec_cam))
            if res.get("ok"):
                st.session_state.pop("kp_va_rec_err", None)
            else:
                st.session_state["kp_va_rec_err"] = res
            st.rerun()
        if b2.button("■  Stop", disabled=not rec_live, use_container_width=True):
            res = screen_recorder.stop()
            if res.get("ok") and res.get("file"):
                st.session_state["kp_va_video_path"] = res["file"]
                st.toast(f"Saved {os.path.basename(res['file'])} — loaded above "
                         "for analysis.")
            st.rerun()

        if rec_live:
            @st.fragment(run_every=1.0)
            def _rec_chip():
                s = screen_recorder.status()
                if s["recording"]:
                    st.markdown(
                        f"<span style='color:#ff3d6e;font-weight:600'>● REC</span> "
                        f"<span style='font-variant-numeric:tabular-nums'>"
                        f"{control.fmt_clock(s['elapsed'])}</span> · "
                        f"{os.path.basename(s['file'] or '')}",
                        unsafe_allow_html=True)
            _rec_chip()

        err = st.session_state.get("kp_va_rec_err")
        if err:
            st.error(err.get("error", "Could not start the webcam recording."))
            if err.get("detail"):
                with st.expander("ffmpeg output"):
                    st.code(err["detail"])

        webcam_recs = [r for r in screen_recorder.list_recordings()
                       if "webcam" in r["name"].lower()]
        if webcam_recs:
            st.caption("Recent webcam recordings:")
            for r in webcam_recs[:6]:
                lc, rc = st.columns([4, 1], vertical_alignment="center")
                lc.caption(f"{r['name']} · {r['size'] / (1024 * 1024):.0f} MB")
                if rc.button("Analyse", key="kp_va_load_" + r["name"]):
                    st.session_state["kp_va_video_path"] = r["path"]
                    st.rerun()

env_key = os.environ.get("ROBOFLOW_API_KEY", "")
roboflow_model = "football-players-detection-3zvbc/12"
model_path = "yolov8m.pt"
api_key = env_key
use_pitch = False
pitch_model = DEFAULT_PITCH_MODEL

m1, m2, m3 = st.columns(3)
selected_device = best_device()
if backend.startswith("Roboflow"):
    with m1:
        roboflow_model = st.text_input("Roboflow model id", value=roboflow_model)
    with m2:
        api_key = st.text_input("Roboflow API key", value=env_key, type="password",
                                help="Free key from roboflow.com → Settings → API key.")
    with m3:
        use_pitch = st.checkbox("Per-frame pitch homography",
                                help="Detects pitch landmarks each frame so "
                                "positions stay accurate on a panning camera.")
        if use_pitch:
            pitch_model = st.text_input("Pitch model id", value=DEFAULT_PITCH_MODEL)
else:
    with m1:
        model_path = st.text_input("Local model weights", value="yolov8m.pt")
    with m2:
        st.caption("Local YOLO uses person/ball (COCO) unless you point it at "
                   "soccer-trained weights.")
    with m3:
        _auto = best_device()
        _device_options = ["auto", "cpu", "mps", "0"]
        _device_labels = {
            "auto": f"Auto ({_auto})",
            "cpu": "CPU",
            "mps": "MPS (Apple Silicon)",
            "0": "CUDA GPU 0",
        }
        _device_choice = st.selectbox(
            "Inference device",
            _device_options,
            format_func=lambda x: _device_labels[x],
        )
        selected_device = _auto if _device_choice == "auto" else _device_choice

s1, s2, s3, s4 = st.columns(4)
stride = s1.slider("Frame stride", 1, 15, 6, help="Process 1 of every N frames.")
if source_kind == "Webcam (live)":
    max_seconds = s2.slider("Max seconds (0 = until stopped)", 0, 1800, 0, 30)
else:
    max_seconds = s2.slider("Max seconds", 5, 120, 20)
conf = s3.slider("Confidence", 0.1, 0.7, 0.25, 0.05)
imgsz = s4.select_slider("Image size", [640, 960, 1280], value=960)

feed_dashboard = st.checkbox(
    "Stream passes into the live dashboard (match_data.json)", value=True,
    help="Bridges detected passes into the event log so the timeline / stats "
    "pages reflect them.")

with st.expander("Tactical map layers", expanded=False):
    r1 = st.columns(4)
    r2 = st.columns(4)
    map_layers = {
        "zones": r1[0].toggle(
            "Zones (18)", value=False,
            help="Six-column x three-row tactical grid, zones 1-18."),
        "half_spaces": r1[1].toggle(
            "Half-spaces", value=False,
            help="Five lanes: wide / half-space / centre / half-space / wide."),
        "thirds": r1[2].toggle(
            "Thirds", value=False,
            help="Defensive / middle / attacking thirds along the play axis."),
        "team_shape": r1[3].toggle(
            "Team shape", value=False,
            help="Convex hull of each team — the space the side occupies."),
        "avg_position": r2[0].toggle(
            "Average position", value=False,
            help="Each team's centroid plus its rear and front player lines."),
        "space_control": r2[1].toggle(
            "Space control", value=False,
            help="Voronoi-style tint of the pitch by nearest team (dynamic)."),
        "passing_lanes": r2[2].toggle(
            "Passing lanes", value=False,
            help="Open vs covered lanes from the likely ball carrier."),
        "ball_trail": r2[3].toggle(
            "Ball trail", value=False,
            help="Fading polyline of the ball's recent path."),
    }

st.divider()


def build_config():
    """Build the PipelineConfig from the current control selections."""
    return PipelineConfig(
        model_path=model_path,
        roboflow_model=roboflow_model if backend.startswith("Roboflow") else "",
        roboflow_api_key=api_key,
        device=selected_device if not backend.startswith("Roboflow") else "cpu",
        detection_imgsz=imgsz,
        frame_stride=stride,
        detection_conf=conf,
        max_seconds=float(max_seconds),
        ocr_enabled=False,
        # Relax possession a touch for the lower sampled frame-rate.
        possession_frames=max(6, 60 // stride),
        # Bound memory for open-ended live sessions; unlimited for files.
        max_frames_recorded=4000 if source_kind == "Webcam (live)" else 0,
        output_path="match_stats.json",
    )


def make_pitch_detector(cfg):
    return (PitchDetector(cfg, pitch_model)
            if (use_pitch and backend.startswith("Roboflow")) else None)


def feed_passes_to_dashboard(stats):
    """Stream detected passes into the dashboard event log (idempotent)."""
    if feed_dashboard and stats.passes:
        events = vbridge.convert(stats.to_dict())
        total = vbridge.write_events(events, "match_data.json",
                                     fresh=False, replace_vision=True)
        st.info(f"Streamed {len(events)} pass event(s) into the dashboard "
                f"({len(total)} events total). Open **Match Timeline** to see them.")


# --------------------------------------------------------------------------- #
# Recorded video — one blocking pass, streamed via callback
# --------------------------------------------------------------------------- #
if source_kind == "Video file":
    if st.button("Run analysis", type="primary", use_container_width=True):
        if not video_path or not os.path.exists(video_path):
            st.error(f"Video not found: {video_path!r}")
            st.stop()
        if backend.startswith("Roboflow") and not api_key:
            st.error("A Roboflow API key is required for the cloud backend.")
            st.stop()

        cfg = build_config()
        analyzer = MatchAnalyzer(cfg, pitch_detector=make_pitch_detector(cfg))
        ph = make_placeholders()
        prog = st.progress(0.0, text="Starting…")
        counters = {"proc": 0, "ball": 0}
        trail = deque(maxlen=25)
        total_frames = max(1, int(max_seconds * 30 / stride))

        def on_det(frame_index, frame, detections, record):
            render_live(ph, analyzer, counters, frame, detections, record,
                        map_layers, trail)
            prog.progress(min(1.0, counters["proc"] / total_frames),
                          text=f"Processing… {record.timestamp}")

        analyzer.on_detections = on_det
        with st.spinner("Analyzing video…"):
            try:
                stats = analyzer.run(video_path)
            except Exception as exc:
                st.error(f"Run failed: {exc}")
                st.stop()

        prog.progress(1.0, text="Done")
        # Keep the passes so the passing map survives reruns (selectbox, etc.).
        st.session_state.kp_va_passes = [p.to_dict() for p in stats.passes]
        poss = stats.possession
        st.success(
            f"Processed {counters['proc']} frames · "
            f"{len(stats.passes)} passes · "
            f"possession Home {poss.team_home_percentage:.0f}% / "
            f"Away {poss.team_away_percentage:.0f}%"
        )
        feed_passes_to_dashboard(stats)
        with open("match_stats.json", "rb") as fh:
            st.download_button("Download match_stats.json", fh,
                               file_name="match_stats.json",
                               mime="application/json")
    else:
        st.caption(
            "Pick a video and a model, then **Run analysis**. The camera view "
            "shows raw detections; the tactical map shows pitch positions from "
            "the homography. Enable **per-frame pitch homography** for panning "
            "cameras.")


# --------------------------------------------------------------------------- #
# Webcam — live stepping loop, so Start/Stop stays responsive
# --------------------------------------------------------------------------- #
else:
    LIVE = "kp_live"
    running = st.session_state.get(LIVE + "_running", False)

    def finalize_live():
        """Stop the camera, assemble stats, and feed the dashboard."""
        analyzer = st.session_state.get(LIVE + "_analyzer")
        if analyzer is not None:
            stats = analyzer.close()
            st.session_state.kp_va_passes = [p.to_dict() for p in stats.passes]
            feed_passes_to_dashboard(stats)
        for k in ("_analyzer", "_running", "_counters", "_trail"):
            st.session_state.pop(LIVE + k, None)

    cstart, cstop = st.columns(2)
    start_clicked = cstart.button("●  Start live", type="primary",
                                  disabled=running, use_container_width=True)
    stop_clicked = cstop.button("■  Stop", disabled=not running,
                                use_container_width=True)

    if start_clicked and not running:
        if backend.startswith("Roboflow") and not api_key:
            st.error("A Roboflow API key is required for the cloud backend.")
            st.stop()
        cfg = build_config()
        try:
            analyzer = MatchAnalyzer(cfg, pitch_detector=make_pitch_detector(cfg))
            analyzer.open(int(cam_index))
        except Exception as exc:
            st.error(f"Could not open camera #{cam_index}: {exc}")
            st.stop()
        st.session_state[LIVE + "_analyzer"] = analyzer
        st.session_state[LIVE + "_running"] = True
        st.session_state[LIVE + "_counters"] = {"proc": 0, "ball": 0}
        st.session_state[LIVE + "_trail"] = deque(maxlen=25)
        st.rerun()

    if stop_clicked and running:
        finalize_live()
        st.toast("Live analysis stopped.")
        st.rerun()

    if st.session_state.get(LIVE + "_running"):
        analyzer = st.session_state[LIVE + "_analyzer"]
        counters = st.session_state[LIVE + "_counters"]
        trail = st.session_state[LIVE + "_trail"]
        st.caption("●  LIVE — analysing webcam. Press **Stop** to finish.")
        ph = make_placeholders()
        ended = False
        for _ in range(2):  # small batch keeps the Stop button responsive
            try:
                out = analyzer.step()
            except Exception as exc:
                st.error(f"Live step failed: {exc}")
                finalize_live()
                st.stop()
            if out is None:        # max_seconds reached or stream closed
                ended = True
                break
            _, frame, dets, record = out
            # Re-read layer toggles each tick so they can be flipped live.
            render_live(ph, analyzer, counters, frame, dets, record,
                        map_layers, trail)
        if ended:
            finalize_live()
            st.success("Live capture finished.")
            st.rerun()
        st.rerun()
    else:
        st.caption(
            "Pick a camera and model, then **Start live**. For useful pitch "
            "analytics mount the camera high and wide so the lines are visible; "
            "a low sideline angle still gives detections but a weak tactical map.")


# --------------------------------------------------------------------------- #
# Passing map (post-run; persists across reruns via session_state)
# --------------------------------------------------------------------------- #
saved_passes = st.session_state.get("kp_va_passes")
if saved_passes:
    st.divider()
    st.markdown("#### Passing map")
    passers = sorted({p["passer"] for p in saved_passes if p.get("passer")})
    sel = st.selectbox("Passer", ["All players"] + passers,
                       help="Filter the map to one player's passes.")
    who = None if sel == "All players" else sel
    st.image(passing_map(saved_passes, who), channels="BGR",
             use_container_width=True,
             caption="Green = completed, red = intercepted / incomplete. "
                     "Arrows run from the ball's start to its end position.")
