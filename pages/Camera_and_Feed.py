#!/usr/bin/env python3
"""
Camera & Feed — set up the Eye before kickoff.

Kickoff Pulse is vision-first: the camera feed is the primary ingest and voice
is the backup. This is where that feed gets configured, tested and calibrated,
so that on match day the console has nothing left to ask you.

Everything here writes to control.json, which the persistent vision runner
(scripts/live_vision.py) reads via vision_runner. Nothing on this page starts an
analysis — that happens on the Match Console.
"""

import os

import streamlit as st

import brand
import control
import ui_helpers as UI
import vision_runner

UI.page_setup("SET UP", "Camera & Feed")

# Heavy vision deps are optional; the page still configures a feed without them,
# it just cannot grab a test frame or calibrate.
try:
    import cv2
    from vision import calibration as vcal
    from vision.runtime import DEVICE_CHOICES, DEVICE_LABELS, best_device
    VISION_OK, VISION_ERR = True, ""
except Exception as exc:  # pragma: no cover - import guard
    VISION_OK, VISION_ERR = False, str(exc)
    DEVICE_CHOICES = ("auto", "cpu", "mps", "0")
    DEVICE_LABELS = {"auto": "Auto", "cpu": "CPU", "mps": "MPS (Apple Silicon)",
                     "0": "CUDA GPU 0"}

# Optional click-to-mark component for fixed-camera pitch calibration.
try:
    from streamlit_image_coordinates import streamlit_image_coordinates
    CLICK_OK = True
except Exception:
    CLICK_OK = False

state = control.load_control()
feed = state["feed"]

if not VISION_OK:
    st.warning("Vision dependencies are not installed, so this page can save a "
               "feed but cannot test or calibrate it.")
    st.code("pip install -r vision/requirements.txt", language="bash")
    st.caption(f"Import error: {VISION_ERR}")


# --------------------------------------------------------------------------- #
# 1. Feed source
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Feed source"), unsafe_allow_html=True)

KINDS = ["stream", "webcam", "file"]
KIND_LABELS = {
    "stream": "Live stream (Veo)",
    "webcam": "Webcam",
    "file": "Video file",
}
kind = st.segmented_control(
    "Source", KINDS, format_func=lambda k: KIND_LABELS[k],
    default=feed.get("kind", "stream"), key="feed_kind",
    help="A live Veo HLS stream is the intended match-day source. Webcam and "
         "file are for testing and for analysing footage after the fact.")
kind = kind or feed.get("kind", "stream")

url = feed.get("url", "")
camera_index = int(feed.get("camera_index", 0) or 0)
file_path = feed.get("file_path", "")

if kind == "stream":
    url = st.text_input(
        "Stream URL", value=url,
        placeholder="https://.../index.m3u8",
        help="A direct HLS/RTSP/RTMP URL is opened straight through FFmpeg. A "
             "YouTube URL also works but is resolved via yt-dlp and is often "
             "capped at 360p, which is too soft for reliable ball detection.")
    st.caption("Veo: open the live match, copy the .m3u8 stream URL. YouTube is "
               "a fallback, not the target.")
elif kind == "webcam":
    cams = []
    try:
        import screen_recorder
        cams = screen_recorder.list_cameras()
    except Exception:
        pass
    if cams:
        labels = {i: f"[{i}] {n}" for i, n in cams}
        options = [i for i, _ in cams]
        camera_index = st.selectbox(
            "Camera", options, format_func=lambda i: labels.get(i, str(i)),
            index=options.index(camera_index) if camera_index in options else 0)
    else:
        camera_index = int(st.number_input(
            "Camera index", min_value=0, max_value=10, value=camera_index,
            step=1, help="Could not auto-list cameras; 0 is usually built-in."))
    st.caption("Mount the camera high and wide so the pitch lines are visible — "
               "a low sideline angle still detects players but gives a weak "
               "tactical map.")
else:
    file_path = st.text_input(
        "Video file path", value=file_path, placeholder="recordings/match.mp4",
        help="Analyse a recording as if it were live. For a one-off pass over "
             "a finished file, the Film Room page is usually a better fit.")

# Persist source edits immediately — there is no Save button for this block, so
# a half-filled form can never disagree with what the runner will open.
feed.update({"kind": kind, "url": url.strip() if isinstance(url, str) else url,
             "camera_index": camera_index, "file_path": file_path.strip()})
state["feed"] = feed
control.save_control(state)


# --------------------------------------------------------------------------- #
# 2. Test connection — the check that used to require running the Eye blind
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Test connection"), unsafe_allow_html=True)

TEST_KEY = "kp_feed_test"


def grab_frame(source):
    """Open the source and return (frame, width, height, fps), warming it first."""
    from vision.sources import resolve_video_source

    resolved = resolve_video_source(source)
    cap = cv2.VideoCapture(resolved.capture_source)
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        # A network stream often needs a few reads before it returns a frame.
        for _ in range(8):
            ok, frame = cap.read()
            if ok and frame is not None:
                return frame, w or frame.shape[1], h or frame.shape[0], fps
        return None, w, h, fps
    finally:
        cap.release()


ready = control.feed_ready(state)
tc1, tc2 = st.columns([1, 2.4], vertical_alignment="center")
if tc1.button("Test connection", type="primary", width="stretch",
              disabled=not (ready and VISION_OK)):
    with st.spinner("Opening the feed…"):
        try:
            frame, w, h, fps = grab_frame(control.feed_source(state))
            if frame is None:
                st.session_state[TEST_KEY] = {
                    "ok": False,
                    "error": "Connected, but no frame arrived. For a live "
                             "stream the match may not have started yet."}
            else:
                st.session_state[TEST_KEY] = {
                    "ok": True, "frame": frame, "w": w, "h": h, "fps": fps}
        except Exception as exc:
            st.session_state[TEST_KEY] = {"ok": False, "error": str(exc)}
    st.rerun()

with tc2:
    if not ready:
        st.caption("Enter a source above to test it.")
    else:
        st.caption(f"Reads one frame from {control.feed_label(state)} and "
                   "reports its resolution — no analysis, no side effects.")

test = st.session_state.get(TEST_KEY)
if test and not test.get("ok"):
    st.error(test.get("error", "Could not open the feed."))
elif test and test.get("ok"):
    w, h, fps = test["w"], test["h"], test["fps"]
    st.success(f"Connected · {w}x{h}" + (f" @ {fps:.0f}fps" if fps else ""))
    if h and h < 720:
        st.warning(f"{h}p is low for ball detection. The ball is only a few "
                   "pixels across below 720p — prefer a 1080p Veo stream.")
    st.image(cv2.cvtColor(test["frame"], cv2.COLOR_BGR2RGB), width="stretch",
             caption="Test frame")


# --------------------------------------------------------------------------- #
# 3. Model & device
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Model & device"), unsafe_allow_html=True)

_auto = best_device() if VISION_OK else "cpu"
_labels = {**DEVICE_LABELS, "auto": f"Auto ({_auto})"}
st.caption(f"{feed.get('model')} on {_labels.get(feed.get('device'), 'Auto')} · "
           f"stride {feed.get('stride')} · {feed.get('imgsz')}px · "
           f"confidence {feed.get('conf')}")

with st.expander("Adjust model, device and sampling"):
    md1, md2 = st.columns(2)
    model = md1.text_input("Model weights", value=feed.get("model", ""),
                           help="Soccer-trained weights give far better ball "
                                "detection than stock COCO weights.")
    _dev = feed.get("device", "auto")
    device = md2.selectbox(
        "Inference device", list(DEVICE_CHOICES),
        index=list(DEVICE_CHOICES).index(_dev) if _dev in DEVICE_CHOICES else 0,
        format_func=lambda d: _labels.get(d, d))

    s1, s2, s3 = st.columns(3)
    stride = s1.slider("Frame stride", 1, 15, int(feed.get("stride", 6)),
                       help="Process 1 of every N frames. Higher keeps a live "
                            "feed real-time on slower hardware.")
    imgsz = s2.select_slider("Image size", [640, 960, 1280],
                             value=int(feed.get("imgsz", 960)))
    conf = s3.slider("Confidence", 0.1, 0.7, float(feed.get("conf", 0.25)), 0.05)

    if st.button("Save model settings", type="primary", width="stretch"):
        state["feed"].update({"model": model.strip(), "device": device,
                              "stride": int(stride), "imgsz": int(imgsz),
                              "conf": float(conf)})
        control.save_control(state)
        st.success("Saved.")
        st.rerun()

    if model.strip() and not os.path.exists(model.strip()) and "/" in model:
        st.warning(f"No file at {model.strip()} — the runner will fail to start.")


# --------------------------------------------------------------------------- #
# 4. Pitch calibration
#
# A fixed camera (Veo) only needs the image->pitch homography set once: mark
# four known landmarks on a grabbed frame and every position from then on
# projects into true pitch coordinates.
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Pitch calibration"), unsafe_allow_html=True)

CAL_KEY = "kp_cal"
saved_cal = vcal.load_calibration() if VISION_OK else None

# A calibration maps pixels to pitch metres only while the camera stays still.
# On an auto-following camera it is stale the moment play moves, so this has to
# be declared rather than assumed — it decides whether calibrated positions can
# be believed at all. See HARDWARE_PROPOSAL.md.
fixed_cam = st.checkbox(
    "The camera is fixed (it does not pan or auto-follow)",
    value=bool(feed.get("fixed_camera", False)),
    help="Veo and similar cameras crop and pan to follow play, which invalidates "
         "a saved calibration continuously. A camera clamped to a mast does not.")
if fixed_cam != bool(feed.get("fixed_camera", False)):
    state["feed"]["fixed_camera"] = fixed_cam
    control.save_control(state)
    st.rerun()

if not fixed_cam:
    st.caption("Because the camera moves, calibration below will not hold for a "
               "whole match and positions stay in image space. A fixed mount is "
               "what makes pitch-accurate positions possible.")

if saved_cal:
    st.success(f"Calibrated · {len(saved_cal['points'])} points · "
               f"saved {saved_cal.get('created', '')}"
               + ("" if fixed_cam else " · but the camera pans, so it goes stale"))
else:
    st.warning(
        "Not calibrated. Analysis still runs, but positions stay in image "
        "space: possession and passing distances are approximate and the "
        "tactical map is a rough projection. Calibrating once per camera "
        "position fixes this for the whole match.")

if VISION_OK and not CLICK_OK:
    st.caption("Click-to-mark needs the image component: "
               "`pip install streamlit-image-coordinates`")
elif VISION_OK:
    gc1, gc2 = st.columns(2)
    if gc1.button("Grab frame to calibrate", width="stretch", disabled=not ready):
        with st.spinner("Grabbing a frame…"):
            try:
                fr, _w, _h, _fps = grab_frame(control.feed_source(state))
            except Exception as exc:
                fr = None
                st.error(f"Could not grab frame: {exc}")
        if fr is not None:
            st.session_state[CAL_KEY + "_frame"] = fr
            st.session_state[CAL_KEY + "_clicks"] = []
            st.session_state.pop(CAL_KEY + "_last", None)
            st.rerun()
    with gc2:
        if UI.confirm_action(
                "Clear saved calibration", key="clear_calibration",
                disabled=not saved_cal,
                warning="Discard the saved pitch calibration? You would need to "
                        "grab a frame and mark all four landmarks again, and "
                        "until then positions stay in image space.",
                confirm_label="Clear it"):
            vcal.clear_calibration()
            st.toast("Calibration cleared.")
            st.rerun()

    frame = st.session_state.get(CAL_KEY + "_frame")
    if frame is not None:
        orig_h, orig_w = frame.shape[:2]
        disp_w = min(900, orig_w)
        f = orig_w / disp_w
        disp_h = int(orig_h / f)
        clicks = st.session_state.setdefault(CAL_KEY + "_clicks", [])

        lm_names = list(vcal.LANDMARKS.keys())
        st.caption("Choose each point's landmark, then click its exact spot on "
                   "the frame — in order.")
        slot_cols = st.columns(4)
        chosen = [
            slot_cols[i].selectbox(
                f"Point {i + 1}", lm_names,
                index=lm_names.index(vcal.DEFAULT_LANDMARK_ORDER[i]),
                key=CAL_KEY + f"_lm{i}")
            for i in range(4)
        ]

        n = len(clicks)
        if n < 4:
            st.info(f"Next: click **{chosen[n]}**  ({n}/4 marked)")
        else:
            st.success("All 4 points marked — review, then Save.")

        disp = cv2.cvtColor(cv2.resize(frame, (disp_w, disp_h)), cv2.COLOR_BGR2RGB)
        for i, (px, py) in enumerate(clicks):
            dx, dy = int(px / f), int(py / f)
            cv2.circle(disp, (dx, dy), 6, (255, 60, 110), 2)
            cv2.putText(disp, str(i + 1), (dx + 8, dy - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 60, 110), 2)

        val = streamlit_image_coordinates(disp, key=CAL_KEY + "_img")
        if val is not None and len(clicks) < 4:
            cur = (val["x"], val["y"])
            if cur != st.session_state.get(CAL_KEY + "_last"):
                st.session_state[CAL_KEY + "_last"] = cur
                clicks.append([cur[0] * f, cur[1] * f])   # store full-res px
                st.rerun()

        bc = st.columns(3)
        if bc[0].button("Undo last", disabled=not clicks, width="stretch"):
            clicks.pop()
            st.rerun()
        if bc[1].button("Reset points", disabled=not clicks, width="stretch"):
            st.session_state[CAL_KEY + "_clicks"] = []
            st.rerun()
        if bc[2].button("Save calibration", type="primary",
                        disabled=len(clicks) < 4, width="stretch"):
            points = [{"label": chosen[i],
                       "norm": list(vcal.LANDMARKS[chosen[i]]),
                       "px": clicks[i]} for i in range(4)]
            try:
                vcal.save_calibration(points, frame_size=(orig_w, orig_h),
                                      source=str(control.feed_source(state)))
                st.toast("Calibration saved.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save: {exc}")


# --------------------------------------------------------------------------- #
# 5. Ingest mode — where vision-first becomes an explicit choice
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Ingest mode"), unsafe_allow_html=True)

modes = list(control.INGEST_MODES)
current = state.get("ingest_mode", "vision")
mode = st.radio(
    "How this match is tracked", modes,
    index=modes.index(current) if current in modes else 0,
    format_func=lambda m: control.INGEST_LABELS[m], label_visibility="collapsed")

MODE_HELP = {
    "vision": "The Eye analyses the camera feed. Nothing listens to your mic — "
              "the quietest option and the default.",
    "both": "The Eye analyses the feed and the mic stays live for the calls "
            "vision can't make: fouls, cards, substitutions, your own notes.",
    "voice": "No camera. The mic-driven tracker logs everything, as the app "
             "worked before. Use this when there's no feed to point at.",
}
st.caption(MODE_HELP[mode])

if mode != current:
    state["ingest_mode"] = mode
    control.save_control(state)
    st.rerun()

if control.uses_vision(state) and not ready:
    st.warning("This mode needs a feed, and none is configured yet. Set one "
               "above before kickoff.")

ok, reason = vision_runner.is_supported()
if control.uses_vision(state) and not ok:
    st.error(reason)

st.divider()
st.caption("Ready? Open the **Match Console** to start the clock and the Eye.")
