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

import numpy as np
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brand           # noqa: E402
import control         # noqa: E402
import icons as IC     # noqa: E402

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


def tactical_map(record, w=520, h=340, show_zones=False, show_half_spaces=False):
    """Top-down pitch with player dots (by team) + ball, from normalised coords.

    ``show_zones`` / ``show_half_spaces`` overlay the 18-zone grid and the
    five-lane half-space bands as toggleable tactical layers.
    """
    pitch = np.full((h, w, 3), (40, 110, 40), dtype=np.uint8)
    cv2.rectangle(pitch, (6, 6), (w - 6, h - 6), (255, 255, 255), 2)
    cv2.line(pitch, (w // 2, 6), (w // 2, h - 6), (255, 255, 255), 1)
    cv2.circle(pitch, (w // 2, h // 2), 46, (255, 255, 255), 1)
    if show_half_spaces:
        _draw_half_spaces(pitch, w, h)
    if show_zones:
        _draw_zones(pitch, w, h)
    for p in record.players:
        cx, cy = int(p.x / 100 * w), int(p.y / 100 * h)
        col = HOME_BGR if p.team == "Home" else AWAY_BGR if p.team == "Away" else (150, 150, 150)
        cv2.circle(pitch, (cx, cy), 6, col, -1)
        cv2.circle(pitch, (cx, cy), 6, (255, 255, 255), 1)
    if record.ball.x is not None:
        bx, by = int(record.ball.x / 100 * w), int(record.ball.y / 100 * h)
        cv2.circle(pitch, (bx, by), 5, (255, 255, 255), -1)
        cv2.circle(pitch, (bx, by), 7, (0, 215, 255), 2)
    return pitch


# --------------------------------------------------------------------------- #
# Controls
# --------------------------------------------------------------------------- #
st.markdown("#### Source & model")
c1, c2 = st.columns([2, 1])
with c1:
    default_video = "soccer_test.mp4" if os.path.exists("soccer_test.mp4") else ""
    video_path = st.text_input("Video file path", value=default_video,
                               placeholder="path/to/match.mp4")
with c2:
    backend = st.radio("Detection backend", ["Roboflow (cloud)", "Local YOLO"],
                       horizontal=False)

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
max_seconds = s2.slider("Max seconds", 5, 120, 20)
conf = s3.slider("Confidence", 0.1, 0.7, 0.25, 0.05)
imgsz = s4.select_slider("Image size", [640, 960, 1280], value=960)

feed_dashboard = st.checkbox(
    "Stream passes into the live dashboard (match_data.json)", value=True,
    help="Bridges detected passes into the event log so the timeline / stats "
    "pages reflect them.")

o1, o2 = st.columns(2)
show_zones = o1.toggle(
    "Tactical map: zones (18)", value=False,
    help="Overlay the six-column x three-row tactical grid (zones 1-18).")
show_half_spaces = o2.toggle(
    "Tactical map: half-spaces", value=False,
    help="Overlay the five lanes: wide / half-space / centre / half-space / wide.")

run = st.button("Run analysis", type="primary", use_container_width=True)
st.divider()


# --------------------------------------------------------------------------- #
# Live run
# --------------------------------------------------------------------------- #
if run:
    if not video_path or not os.path.exists(video_path):
        st.error(f"Video not found: {video_path!r}")
        st.stop()
    if backend.startswith("Roboflow") and not api_key:
        st.error("A Roboflow API key is required for the cloud backend.")
        st.stop()

    cfg = PipelineConfig(
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
        output_path="match_stats.json",
    )
    pitch_detector = (
        PitchDetector(cfg, pitch_model)
        if (use_pitch and backend.startswith("Roboflow")) else None
    )

    # --- live placeholders ------------------------------------------------- #
    v_col, t_col = st.columns(2)
    frame_ph = v_col.empty()
    map_ph = t_col.empty()
    mrow = st.columns(5)
    ph_proc, ph_players, ph_ball, ph_poss, ph_pass = [c.empty() for c in mrow]
    feed_ph = st.empty()
    prog = st.progress(0.0, text="Starting…")

    counters = {"proc": 0, "ball": 0}
    total_frames = max(1, int(max_seconds * 30 / stride))

    analyzer = MatchAnalyzer(cfg, pitch_detector=pitch_detector)

    def on_det(frame_index, frame, detections, record):
        counters["proc"] += 1
        n_players = sum(1 for d in detections if d.cls_name == "player")
        has_ball = any(d.cls_name == "ball" for d in detections)
        counters["ball"] += 1 if has_ball else 0

        frame_ph.image(annotate(frame, detections), channels="BGR",
                       use_container_width=True, caption=f"Camera · {record.timestamp}")
        map_ph.image(tactical_map(record, show_zones=show_zones,
                                  show_half_spaces=show_half_spaces),
                     channels="BGR", use_container_width=True,
                     caption="Tactical map")

        poss = analyzer.engine.possession_summary()
        events = analyzer.engine.events
        ball_pct = 100 * counters["ball"] / max(1, counters["proc"])
        ph_proc.metric("Frames", counters["proc"])
        ph_players.metric("Players", n_players)
        ph_ball.metric("Ball seen", f"{ball_pct:.0f}%")
        ph_poss.metric("Possession H/A",
                       f"{poss.team_home_percentage:.0f}/{poss.team_away_percentage:.0f}")
        ph_pass.metric("Passes", len(events))

        if events:
            lines = []
            for e in events[-5:][::-1]:
                d = e.to_dict()
                lines.append(
                    f"`{d['timestamp']}` **{d['passer']}** → "
                    f"{d['intended_receiver'] or '—'} · {d['pass_type'].replace('_',' ')} "
                    f"· _{d['outcome']}_")
            feed_ph.markdown("**Recent passes**\n\n" + "\n\n".join(lines))
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
    poss = stats.possession
    st.success(
        f"Processed {counters['proc']} frames · "
        f"{len(stats.passes)} passes · "
        f"possession Home {poss.team_home_percentage:.0f}% / "
        f"Away {poss.team_away_percentage:.0f}%"
    )

    # Feed the dashboard event log (idempotent: replaces prior vision events).
    if feed_dashboard and stats.passes:
        events = vbridge.convert(stats.to_dict())
        total = vbridge.write_events(events, "match_data.json",
                                     fresh=False, replace_vision=True)
        st.info(f"Streamed {len(events)} pass event(s) into the dashboard "
                f"({len(total)} events total). Open **Match Timeline** to see them.")

    with open("match_stats.json", "rb") as fh:
        st.download_button("Download match_stats.json", fh,
                           file_name="match_stats.json", mime="application/json")
else:
    st.caption(
        "Pick a video and a model, then **Run analysis**. The camera view shows "
        "raw detections; the tactical map shows pitch positions from the "
        "homography. Enable **per-frame pitch homography** for panning cameras."
    )
