#!/usr/bin/env python3
"""
Live Eye — the full-size view of the vision runner.

The vision pipeline (the Eye) runs as its own persistent process
(scripts/live_vision.py), so it keeps analysing the match no matter where you
click. This page is a window onto that process: the latest annotated frame at
full width plus the live possession / passing figures.

Same controls as the Match Console, so you can start, pause at half-time and
stop from whichever page you happen to be on. Navigating away never stops a run.
"""

import streamlit as st

import brand
import control
import ui_helpers as UI
import vision_runner

st.markdown(brand.app_css(), unsafe_allow_html=True)
st.markdown(brand.page_header("LIVE EYE", "Vision runner"), unsafe_allow_html=True)

state = control.load_control()

if not control.uses_vision(state):
    st.warning("This match is set to voice-only, so the Eye is not part of it. "
               "Switch the ingest mode on **Camera & Feed** to use vision.")

# Controls first and outside the fragment, so a click always registers.
UI.render_eye_controls(state, key_prefix="liveeye")

st.divider()


def render():
    st_v = vision_runner.status()
    chips = st.columns(4)
    chips[0].metric("Possession Home", f"{st_v['possession_home']:.0f}%")
    chips[1].metric("Possession Away", f"{st_v['possession_away']:.0f}%")
    chips[2].metric("Passes", st_v["passes"])
    chips[3].metric("Ball detected", f"{st_v['ball_rate'] * 100:.0f}%")
    UI.render_eye_frame()


# 1s auto-refreshing fragment. The runner owns the capture loop; this page only
# displays what it writes.
UI.live_fragment(render)
