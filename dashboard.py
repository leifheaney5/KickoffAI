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
# Club mode gate.
#
# Authentication is opt-in: with no accounts defined the app is unrestricted and
# a single coach never sees a login screen. Once a club creates its first
# account, everything but Account requires signing in.
# --------------------------------------------------------------------------- #
try:
    import auth
    _auth_on = auth.auth_enabled()
    _me = auth.current_user() if _auth_on else None
except Exception:
    _auth_on, _me = False, None

if _auth_on and not _me:
    st.navigation([st.Page("pages/Account.py", title="Sign in",
                           icon=":material/login:")]).run()
    st.stop()

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
        # Identity and remote viewing — not workflow steps, which is why they sit
        # apart from the match-day groups above rather than padding one of them.
        # Rule of thumb for this nav: about four entries per group, and a group
        # earns its place only by mapping to a distinct moment in the match day.
        "You": [
            st.Page("pages/Account.py",
                    title=(_me["display_name"] if _me else "Account"),
                    icon=":material/account_circle:"),
            st.Page("pages/Sideline.py", title="Sideline view",
                    icon=":material/smartphone:"),
        ],
    }
)
nav.run()
