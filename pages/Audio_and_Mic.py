#!/usr/bin/env python3
"""
Audio & Mic — tune what the tracker hears.

Background block-out (live mic sensitivity), audio chunking, a mic calibration
test, screen + mic capture, and the voice phrasing guide. These are the dials
you set once for your room and rarely touch mid-match.
"""

import os

import streamlit as st

import brand
import control
import screen_recorder
import ui_helpers as UI

st.markdown(brand.app_css(), unsafe_allow_html=True)
st.markdown(brand.page_header("SET UP", "Audio & Mic"), unsafe_allow_html=True)

state = control.load_control()

# ---- Background block-out (live mic sensitivity) -------------------------- #
st.markdown(brand.section("Background block-out"), unsafe_allow_html=True)
gate = st.slider(
    "Block-out strength", min_value=0, max_value=100,
    value=int(state.get("noise_gate", control.DEFAULT_NOISE_GATE)),
    label_visibility="collapsed", key="noise_gate_slider",
    help="Higher blocks more background noise — only louder, closer speech is "
         "tracked. Lower is more sensitive. Takes effect immediately.")
if gate != int(state.get("noise_gate", control.DEFAULT_NOISE_GATE)):
    state["noise_gate"] = gate
    control.save_control(state)
st.caption(f"More sensitive  ·  strength {gate}/100  ·  blocks more  —  "
           f"only sound above ~{control.gate_to_threshold(gate):.0f} energy is "
           f"captured. Watch the “Heard” chip and adjust to taste.")

UI.render_audio_chunking_controls(state)
UI.render_mic_calibration(state)

st.write("")

# ---- Voice phrasing guide ------------------------------------------------- #
st.markdown(brand.section("Voice guide"), unsafe_allow_html=True)
UI.render_voice_guide()

st.write("")

# ---- Screen capture (records the screen + mic to a video file) ------------ #
st.markdown(brand.section("Screen capture"), unsafe_allow_html=True)
if not screen_recorder.is_supported():
    st.caption("Screen recording needs macOS with ffmpeg installed "
               "(`brew install ffmpeg`).")
else:
    recording = screen_recorder.status()["recording"]
    sc1, sc2 = st.columns([1, 2.4], vertical_alignment="center")
    if sc1.button("⬛  Stop capture" if recording else "●  Record screen",
                  type="primary" if recording else "secondary",
                  width="stretch", key="screen_capture_toggle"):
        if recording:
            res = screen_recorder.stop()
            st.toast(f"Saved {os.path.basename(res['file'])}" if res.get("ok")
                     else res.get("error", "Could not stop recording."))
        else:
            res = screen_recorder.start(label=state.get("match_name", ""))
            if res.get("ok"):
                st.session_state.pop("screen_capture_error", None)
            else:
                st.session_state["screen_capture_error"] = res
        st.rerun()

    with sc2:
        UI.live_fragment(UI.render_capture_indicator)

    err = st.session_state.get("screen_capture_error")
    if err:
        st.error(err.get("error", "Could not start recording."))
        if err.get("detail"):
            with st.expander("ffmpeg output"):
                st.code(err["detail"])

    recs = screen_recorder.list_recordings()
    if recs:
        with st.expander(f"Recordings ({len(recs)})"):
            for r in recs[:12]:
                mb = r["size"] / (1024 * 1024)
                st.caption(f"{r['name']} · {mb:.0f} MB · {r['path']}")
