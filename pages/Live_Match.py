#!/usr/bin/env python3
"""
Live Match — the match console.

The home of the app during a game: the hero scoreboard with a 90-minute clock,
live status chips, the transport controls, the real-time event feed + stats, and
free-form thought notes. Everything you touch while the whistle is live and
nothing you don't — setup, audio tuning and post-match export live on their own
pages.
"""

import streamlit as st

import brand
import control
import screen_recorder
import stats as S
import ui_helpers as UI

st.markdown(brand.app_css(), unsafe_allow_html=True)

events = S.load_events()
state = control.load_control()

# ---- Hero: logo + editable match title ------------------------------------ #
UI.render_match_title(state, events)
st.write("")

# ---- Live status chips ---------------------------------------------------- #
UI.live_fragment(UI.render_status_chips)
st.write("")

# ---- Hero scoreboard ------------------------------------------------------ #
UI.live_fragment(UI.render_scoreboard)
st.write("")

# ---- Transport controls (outside any fragment so clicks never get cut off) - #
ctl = st.columns([1, 1, 1, 1, 1.4], vertical_alignment="bottom")
if ctl[0].button("▶  Start", width="stretch"):
    control.save_control(control.timer_start(state))
    # Auto-start screen capture alongside the match clock (no-op if already
    # recording or unsupported).
    if (screen_recorder.is_supported()
            and not screen_recorder.status()["recording"]):
        res = screen_recorder.start(label=state.get("match_name", ""))
        if not res.get("ok"):
            st.session_state["screen_capture_error"] = res
    st.rerun()
if ctl[1].button("⏸  Pause", width="stretch"):
    control.save_control(control.timer_pause(state)); st.rerun()
if ctl[2].button("⯀  Half", width="stretch"):
    control.save_control(control.timer_halftime(state)); st.rerun()
if ctl[3].button("↺  Reset", width="stretch"):
    control.save_control(control.timer_reset(state)); st.rerun()
paused = state.get("paused", False)
rec_label = "● Resume recording" if paused else "● Pause recording"
if ctl[4].button(rec_label, width="stretch",
                 type="primary" if paused else "secondary"):
    state["paused"] = not paused
    control.save_control(state)
    st.rerun()
st.caption("Recording paused — new events are not logged." if paused
           else "Recording — narrate the match into your mic.")

UI.render_voice_guide()

undo_col, _ = st.columns([1, 4])
if events and undo_col.button("Undo last event", width="stretch"):
    removed = S.pop_last_event()
    if removed:
        kind = removed.get("action") or "event"
        st.toast(f"Removed: {kind} ({removed.get('team') or 'unknown team'})")

st.write("")

# ---- Record thoughts / synopsis ------------------------------------------- #
st.markdown(brand.section("Record thoughts / synopsis"), unsafe_allow_html=True)
thoughts_on = state.get("thoughts_mode", False)
th1, th2 = st.columns([1, 2.4], vertical_alignment="center")
if th1.button("● Stop recording" if thoughts_on else "Record thoughts",
              type="primary" if thoughts_on else "secondary", width="stretch",
              key="thoughts_toggle"):
    state["thoughts_mode"] = not thoughts_on
    control.save_control(state)
    st.rerun()
with th2:
    if thoughts_on:
        st.caption("Recording — speak your thoughts freely. Each phrase is saved "
                   "as a note below (match events are paused). Click Stop when done.")
    else:
        st.caption("Click, then speak a free-form synopsis or observation. Your "
                   "words are saved as timestamped notes instead of match events.")

notes = control.load_notes()
if notes:
    for n in reversed(notes[-30:]):
        nc1, nc2 = st.columns([12, 1], vertical_alignment="center")
        nc1.markdown(
            f"<div class='kp-feed'><div class='body'><div class='top'>"
            f"<span class='t'>{n.get('match_time') or ''}</span></div>"
            f"<div class='sum'>{n.get('text', '')}</div></div></div>",
            unsafe_allow_html=True)
        if nc2.button("✕", key=f"delnote_{n['timestamp']}", help="Delete note"):
            control.delete_note(n["timestamp"])
            st.rerun()
else:
    st.caption("No notes yet.")

st.write("")

# ---- Live stats + feed ---------------------------------------------------- #
if hasattr(st, "fragment"):
    st.fragment(run_every=1.0)(UI.render_stats_feed)()
else:
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=2000, key="kickoff_refresh")
    except ImportError:
        pass
    UI.render_stats_feed()
