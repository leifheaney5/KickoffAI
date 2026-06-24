#!/usr/bin/env python3
"""
Kickoff Pulse — app entry point / router.

This file no longer renders the home screen itself. It sets up the design system
and defines the grouped navigation; each screen lives in its own page under
pages/. The live match console (the old home page) is pages/Live_Match.py.

Run via:  streamlit run dashboard.py   (or use ./kickoff.sh / .\\kickoff.ps1)
"""

import streamlit as st

import brand

st.set_page_config(page_title=brand.NAME, page_icon=brand.LOGO_TRANSPARENT,
                   layout="wide")
st.markdown(brand.app_css(), unsafe_allow_html=True)
if not st.session_state.get("kp_splash_seen"):
    st.session_state["kp_splash_seen"] = True
    st.markdown(brand.loading_splash(), unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Grouped navigation — a clean, lifecycle-ordered sidebar:
#   Live  →  Set up  →  Analysis  →  After match
# --------------------------------------------------------------------------- #
nav = st.navigation(
    {
        "Live": [
            st.Page("pages/Live_Match.py", title="Live Match",
                    icon=":material/sports_soccer:", default=True),
        ],
        "Set up": [
            st.Page("pages/Match_Setup.py", title="Match Setup",
                    icon=":material/tune:"),
            st.Page("pages/Audio_and_Mic.py", title="Audio & Mic",
                    icon=":material/mic:"),
        ],
        "Analysis": [
            st.Page("pages/1_Match_Timeline.py", title="Timeline",
                    icon=":material/timeline:"),
            st.Page("pages/2_Match_Insights.py", title="Insights",
                    icon=":material/insights:"),
            st.Page("pages/3_Manual_Entry.py", title="Manual Entry",
                    icon=":material/edit_note:"),
            st.Page("pages/4_Video_Analysis.py", title="Video Analysis",
                    icon=":material/videocam:"),
            st.Page("pages/5_Team_Shape.py", title="Team Shape",
                    icon=":material/groups:"),
        ],
        "After match": [
            st.Page("pages/Post_Match.py", title="Post-Match",
                    icon=":material/summarize:"),
            st.Page("pages/6_Match_Library.py", title="Match Library",
                    icon=":material/video_library:"),
            st.Page("pages/7_Season.py", title="Season",
                    icon=":material/leaderboard:"),
            st.Page("pages/8_Analyst.py", title="Analyst",
                    icon=":material/auto_awesome:"),
        ],
    }
)
nav.run()
