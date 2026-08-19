#!/usr/bin/env python3
"""
Sideline — the read-only phone view.

A coach during a match is on the touchline, not at a laptop. Streamlit already
serves over HTTP; with KICKOFF_LAN=1 the launcher binds it to the local network
so a phone on the same wifi can watch the match state.

Deliberately **read-only**: scoreboard, the Eye's latest frame, recent events,
and nothing that writes. A phone cannot disturb a live capture, which is the
whole reason this is safe to expose at all.
"""

import streamlit as st

import auth
import brand
import control
import stats as S
import ui_helpers as UI

UI.page_setup()

# Strip the app chrome a phone can never use, and let the frame go full width.
st.markdown("<style>section[data-testid='stSidebar']{display:none}"
            "div.block-container{padding-top:.8rem;max-width:100%}</style>",
            unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Access
#
# Club mode wins where it is on. Otherwise a LAN-bound app asks for the shared
# code: binding to the network is already opt-in, but "anyone on the wifi can
# watch" should be a decision, not a surprise.
# --------------------------------------------------------------------------- #
code_key = "kp_sideline_code"
ok, why = auth.sideline_allowed(st.session_state.get(code_key))
if not ok:
    st.markdown(brand.page_header("SIDELINE", "Match view"),
                unsafe_allow_html=True)
    st.info(why)
    if not auth.auth_enabled():
        entered = st.text_input("Access code", type="password")
        if st.button("View the match", type="primary", width="stretch"):
            if auth.sideline_allowed(entered)[0]:
                st.session_state[code_key] = entered
                st.rerun()
            else:
                st.error("That code is not right.")
    st.stop()


def render():
    state = control.load_control()
    events = S.load_events()

    UI.render_scoreboard()
    st.write("")
    UI.render_status_chips()
    st.write("")

    if control.uses_vision(state):
        UI.render_eye_frame()
        st.write("")

    st.markdown(brand.section("Latest"), unsafe_allow_html=True)
    recent = [e for e in events if e.get("status") != "denied"][-8:][::-1]
    if not recent:
        st.caption("Nothing logged yet.")
        return
    for e in recent:
        st.markdown(
            f"<div class='kp-feed'><div class='body'><div class='top'>"
            f"<span class='t'>{UI.event_time(e)}</span>&nbsp;&nbsp;"
            f"{UI.team_chip(e.get('team'))}</div>"
            f"<div class='sum'>{UI.event_summary(e)}</div></div></div>",
            unsafe_allow_html=True)


# Same 1s refresh as the console: this is a window onto a live match.
UI.live_fragment(render)
st.caption("Read-only view — the match is controlled from the laptop.")
