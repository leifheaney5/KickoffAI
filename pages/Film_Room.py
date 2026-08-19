#!/usr/bin/env python3
"""
Film Room — analyse recorded footage.

One blocking pass over a video file, streamed into the UI as it goes: an
annotated camera frame, a top-down tactical map built from the pitch homography,
and the resulting possession / passing stats. Detected passes can be bridged
into the dashboard's event log so the timeline and stats pages reflect them.

Live sources are deliberately NOT handled here. A live match runs through the
persistent vision runner (the Eye) from the Match Console, which keeps analysing
wherever you navigate; this page's stepping loop only ran while it was the
active script, so a live run died the moment you clicked away. Feed and model
settings live on Camera & Feed.
"""

import os
from collections import deque

import streamlit as st

import brand           # noqa: E402
import control         # noqa: E402
import screen_recorder  # noqa: E402
import ui_helpers as UI  # noqa: E402

# Heavy vision deps are optional; fail gracefully with install guidance.
try:
    from vision import MatchAnalyzer, PipelineConfig
    from vision import bridge as vbridge
    from vision import calibration as vcal
    from vision import render as VR
    from vision.pitch import DEFAULT_PITCH_MODEL, PitchDetector
    from vision.runtime import DEVICE_CHOICES, DEVICE_LABELS, best_device
    VISION_OK, VISION_ERR = True, ""
except Exception as exc:  # pragma: no cover - import guard
    VISION_OK, VISION_ERR = False, str(exc)

state = control.load_control()
match_name = (state.get("match_name") or "").strip()
UI.page_setup("FILM ROOM", match_name or "Recorded analysis")

if not VISION_OK:
    st.error("Vision dependencies are not installed.")
    st.code("pip install -r vision/requirements.txt", language="bash")
    st.caption(f"Import error: {VISION_ERR}")
    st.stop()


# --------------------------------------------------------------------------- #
# Live-run helpers
# --------------------------------------------------------------------------- #
def make_placeholders():
    """Create the live view placeholders: source frame, map, metrics, feed."""
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
    ph["frame"].image(VR.annotate(frame, dets), channels="BGR",
                      use_container_width=True,
                      caption=f"Camera · {record.timestamp}")
    ph["map"].image(VR.tactical_map(record, layers=map_layers,
                                    ball_trail=list(trail)),
                    channels="BGR", use_container_width=True,
                    caption="Tactical map")
    poss = analyzer.engine.possession_summary()
    events = analyzer.engine.events
    ball_pct = 100 * counters["ball"] / max(1, counters["proc"])
    ph["proc"].metric("Frames", counters["proc"])
    ph["players"].metric("Players", n_players)
    ph["ball"].metric("Ball seen", f"{ball_pct:.0f}%")
    ph["poss"].metric("Possession H/A",
                      f"{poss.team_home_percentage:.0f}/"
                      f"{poss.team_away_percentage:.0f}")
    ph["pass"].metric("Passes", len(events))
    if events:
        lines = []
        for e in events[-5:][::-1]:
            d = e.to_dict()
            lines.append(
                f"`{d['timestamp']}` **{d['passer']}** → "
                f"{d['intended_receiver'] or '—'} · "
                f"{d['pass_type'].replace('_', ' ')} · _{d['outcome']}_")
        ph["feed"].markdown("**Recent passes**\n\n" + "\n\n".join(lines))


# --------------------------------------------------------------------------- #
# Source — a file, and a way to make one
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Footage"), unsafe_allow_html=True)

_default = state["feed"].get("file_path") or (
    "soccer_test.mp4" if os.path.exists("soccer_test.mp4") else "")
video_path = st.text_input(
    "Video file path", value=st.session_state.get("kp_va_video_path", _default),
    placeholder="recordings/match.mp4",
    help="A finished recording. For a live match use the Match Console instead.")

if screen_recorder.is_supported():
    with st.expander("Record from a webcam first"):
        rec = screen_recorder.status()
        rec_live = rec["recording"] and rec.get("kind") == "webcam"
        cams = screen_recorder.list_cameras()
        cam_names = dict(cams)
        if cams:
            rec_cam = st.selectbox(
                "Webcam", [i for i, _ in cams],
                format_func=lambda i: f"[{i}] {cam_names.get(i, '')}",
                disabled=rec["recording"], key="kp_va_rec_cam")
        else:
            rec_cam = st.number_input("Camera index", 0, 10, 0, 1,
                                      disabled=rec["recording"],
                                      key="kp_va_rec_cam")
        b1, b2 = st.columns(2)
        if b1.button("●  Record webcam", type="primary",
                     disabled=rec["recording"], width="stretch"):
            res = screen_recorder.start(label=match_name, source=int(rec_cam))
            if res.get("ok"):
                st.session_state.pop("kp_va_rec_err", None)
            else:
                st.session_state["kp_va_rec_err"] = res
            st.rerun()
        if b2.button("■  Stop", disabled=not rec_live, width="stretch"):
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


# --------------------------------------------------------------------------- #
# Model & sampling — seeded from the saved feed config so a file run matches
# what the Eye would do live, while staying overridable for one-off experiments.
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Detection"), unsafe_allow_html=True)

feed = state["feed"]
env_key = os.environ.get("ROBOFLOW_API_KEY", "")
roboflow_model = "football-players-detection-3zvbc/12"
api_key = env_key
use_pitch = False
pitch_model = DEFAULT_PITCH_MODEL

backend = st.radio("Detection backend", ["Local YOLO", "Roboflow (cloud)"],
                   horizontal=True)
is_roboflow = backend.startswith("Roboflow")

m1, m2, m3 = st.columns(3)
model_path = feed.get("model", "yolov8m.pt")
selected_device = best_device()
if is_roboflow:
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
        model_path = st.text_input("Local model weights", value=model_path)
    with m2:
        st.caption("Local YOLO uses person/ball (COCO) unless you point it at "
                   "soccer-trained weights.")
    with m3:
        _auto = best_device()
        _labels = {**DEVICE_LABELS, "auto": f"Auto ({_auto})"}
        _choice = st.selectbox("Inference device", list(DEVICE_CHOICES),
                               format_func=lambda x: _labels[x])
        selected_device = _auto if _choice == "auto" else _choice

s1, s2, s3, s4 = st.columns(4)
stride = s1.slider("Frame stride", 1, 15, int(feed.get("stride", 6)),
                   help="Process 1 of every N frames.")
max_seconds = s2.slider("Max seconds", 5, 120, 20)
conf = s3.slider("Confidence", 0.1, 0.7, float(feed.get("conf", 0.25)), 0.05)
imgsz = s4.select_slider("Image size", [640, 960, 1280],
                         value=int(feed.get("imgsz", 960)))

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


# --------------------------------------------------------------------------- #
# Calibration — configured on Camera & Feed; shown here so a run is never a
# surprise about which coordinate space it produced.
# --------------------------------------------------------------------------- #
saved_cal = vcal.load_calibration()
use_calibration = st.checkbox(
    "Use fixed-camera calibration", value=bool(saved_cal), disabled=not saved_cal,
    help="Project positions through the saved 4-point homography instead of "
         "naive image space. Overrides per-frame pitch homography.")
if not saved_cal:
    st.caption("Not calibrated — positions stay in image space. Calibrate on "
               "**Camera & Feed** for true pitch coordinates.")

cal_homography = None
if use_calibration and saved_cal:
    try:
        cal_homography = vcal.homography_from_calibration(saved_cal)
    except Exception as exc:
        st.warning(f"Calibration unusable ({exc}); using image space.")

st.divider()


def build_config():
    """Build the PipelineConfig from the current control selections."""
    return PipelineConfig(
        model_path=model_path,
        roboflow_model=roboflow_model if is_roboflow else "",
        roboflow_api_key=api_key,
        device="cpu" if is_roboflow else selected_device,
        detection_imgsz=imgsz,
        frame_stride=stride,
        detection_conf=conf,
        max_seconds=float(max_seconds),
        ocr_enabled=False,
        # Relax possession a touch for the lower sampled frame-rate.
        possession_frames=max(6, 60 // stride),
        max_frames_recorded=0,          # a file run is bounded already
        output_path="match_stats.json",
    )


def make_analyzer(cfg):
    """Build a MatchAnalyzer wired with the fixed-camera homography if calibrated.

    A static calibration and the per-frame pitch detector are mutually exclusive
    (the detector overwrites the homography each frame), so calibration wins.
    """
    pd = None
    if cal_homography is None and use_pitch and is_roboflow:
        pd = PitchDetector(cfg, pitch_model)
    return MatchAnalyzer(cfg, homography=cal_homography, pitch_detector=pd)


def feed_passes_to_dashboard(stats):
    """Stream detected passes into the dashboard event log (idempotent)."""
    if feed_dashboard and stats.passes:
        events = vbridge.convert(stats.to_dict())
        total = vbridge.write_events(events, "match_data.json",
                                     fresh=False, replace_vision=True)
        st.info(f"Streamed {len(events)} pass event(s) into the dashboard "
                f"({len(total)} events total). Open **Timeline** to see them.")


# --------------------------------------------------------------------------- #
# Run — one blocking pass, streamed via callback
# --------------------------------------------------------------------------- #
if st.button("Run analysis", type="primary", width="stretch"):
    if not video_path or not os.path.exists(video_path):
        st.error(f"Video not found: {video_path!r}")
        st.stop()
    if is_roboflow and not api_key:
        st.error("A Roboflow API key is required for the cloud backend.")
        st.stop()

    cfg = build_config()
    analyzer = make_analyzer(cfg)
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
        f"Processed {counters['proc']} frames · {len(stats.passes)} passes · "
        f"possession Home {poss.team_home_percentage:.0f}% / "
        f"Away {poss.team_away_percentage:.0f}%")
    feed_passes_to_dashboard(stats)
    with open("match_stats.json", "rb") as fh:
        st.download_button("Download match_stats.json", fh,
                           file_name="match_stats.json",
                           mime="application/json")
else:
    st.caption(
        "Pick a video and a model, then **Run analysis**. The camera view shows "
        "raw detections; the tactical map shows pitch positions from the "
        "homography. Analysing a live match? Use the **Match Console** — the "
        "Eye keeps running there wherever you navigate.")


# --------------------------------------------------------------------------- #
# Passing map (post-run; persists across reruns via session_state)
# --------------------------------------------------------------------------- #
saved_passes = st.session_state.get("kp_va_passes")
if saved_passes:
    st.divider()
    st.markdown(brand.section("Passing map"), unsafe_allow_html=True)
    passers = sorted({p["passer"] for p in saved_passes if p.get("passer")})
    sel = st.selectbox("Passer", ["All players"] + passers,
                       help="Filter the map to one player's passes.")
    who = None if sel == "All players" else sel
    st.image(VR.passing_map(saved_passes, who), channels="BGR",
             use_container_width=True,
             caption="Green = completed, red = intercepted / incomplete. "
                     "Arrows run from the ball's start to its end position.")
