#!/usr/bin/env python3
"""
Kickoff Pulse — app entry point / router.

This file no longer renders the home screen itself. It sets up the design system
and defines the grouped navigation; each screen lives in its own page under
pages/. The match console (the old home page) is pages/Match_Console.py.

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
# Grouped navigation — lifecycle-ordered, vision-first:
#   Set up  →  Live  →  Analysis  →  After match
#
# Two rules keep this readable as the app grows:
#   1. Groups follow the order you actually touch them across a match day. You
#      configure a feed before kickoff, so "Set up" comes first.
#   2. Within a group, the visual ingest path leads and the fallbacks follow.
#      Camera & Feed sits above Voice Backup; the Live group runs Console (the
#      hub) → Live Eye (the vision view) → Manual Entry (type it yourself).
# --------------------------------------------------------------------------- #
nav = st.navigation(
    {
        "Set up": [
            st.Page("pages/Match_Setup.py", title="Match Setup",
                    icon=":material/tune:"),
            st.Page("pages/Camera_and_Feed.py", title="Camera & Feed",
                    icon=":material/videocam:"),
            st.Page("pages/Voice_Backup.py", title="Voice Backup",
                    icon=":material/mic:"),
        ],
        "Live": [
            st.Page("pages/Match_Console.py", title="Match Console",
                    icon=":material/sports_soccer:", default=True),
            st.Page("pages/Live_Eye.py", title="Live Eye",
                    icon=":material/visibility:"),
            st.Page("pages/Manual_Entry.py", title="Manual Entry",
                    icon=":material/edit_note:"),
        ],
        "Analysis": [
            st.Page("pages/Timeline.py", title="Timeline",
                    icon=":material/timeline:"),
            st.Page("pages/Insights.py", title="Insights",
                    icon=":material/insights:"),
            st.Page("pages/Team_Shape.py", title="Team Shape",
                    icon=":material/groups:"),
            st.Page("pages/Film_Room.py", title="Film Room",
                    icon=":material/movie:"),
        ],
        "After match": [
            st.Page("pages/Post_Match.py", title="Post-Match",
                    icon=":material/summarize:"),
            st.Page("pages/Match_Library.py", title="Match Library",
                    icon=":material/video_library:"),
            st.Page("pages/Season.py", title="Season",
                    icon=":material/leaderboard:"),
            st.Page("pages/Analyst.py", title="Analyst",
                    icon=":material/auto_awesome:"),
        ],
    }
)
nav.run()
