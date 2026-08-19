#!/usr/bin/env python3
"""
Match Console — the hub during a game.

The hero scoreboard with a 90-minute clock, live status for whichever ingest
paths this match uses, one transport that drives the match clock and the Eye
together, and the real-time event feed and stats.

Vision leads: the Eye's live frame and controls sit directly under the
scoreboard. The voice sections (thought notes, the phrasing guide) render only
when the match is configured to use the mic, so a vision-only match isn't asked
to think about a microphone at all.
"""

import streamlit as st

import brand
import control
import screen_recorder
import stats as S
import ui_helpers as UI
import vision_runner

UI.page_setup()

events = S.load_events()
state = control.load_control()
use_vision = control.uses_vision(state)
use_voice = control.uses_voice(state)

# ---- Hero: logo + editable match title ------------------------------------ #
UI.render_match_title(state, events)
st.write("")

# ---- First run: say what is still needed, then get out of the way ---------- #
if UI.render_get_started(state):
    st.write("")

# ---- Live status chips (ingest-aware) ------------------------------------- #
UI.live_fragment(UI.render_status_chips)
st.write("")

# ---- Hero scoreboard ------------------------------------------------------ #
UI.live_fragment(UI.render_scoreboard)
st.write("")

# --------------------------------------------------------------------------- #
# Transport — one set of controls for the match, driving every active ingest.
# Kept outside any fragment so clicks are never cut off by an auto-refresh.
# --------------------------------------------------------------------------- #
ctl = st.columns([1, 1, 1, 1, 1.4], vertical_alignment="bottom")

if ctl[0].button("▶  Start", width="stretch"):
    control.save_control(control.timer_start(state))
    # Start every ingest the match is configured for, so the transport means
    # one thing: "the match is live". A failure here must never block the clock.
    if use_vision and not vision_runner.status()["running"]:
        res = vision_runner.start(state)
        if not res.get("ok"):
            st.session_state["eye_error"] = res
    if (screen_recorder.is_supported()
            and not screen_recorder.status()["recording"]):
        res = screen_recorder.start(label=state.get("match_name", ""))
        if not res.get("ok"):
            st.session_state["screen_capture_error"] = res
    st.rerun()

if ctl[1].button("⏸  Pause", width="stretch"):
    control.save_control(control.timer_pause(state))
    st.rerun()

if ctl[2].button("⯀  Half", width="stretch"):
    control.save_control(control.timer_halftime(state))
    # Half-time idles the Eye: it releases the capture and keeps every
    # accumulated stat, then re-opens from the live edge on resume.
    if use_vision and vision_runner.status()["running"]:
        vision_runner.pause()
    st.rerun()

# Reset is the one transport control that destroys something: the match clock
# cannot be re-run. Guarded only when there is a clock worth losing, so a stray
# click before kickoff still costs nothing.
_elapsed = control.elapsed_seconds(state["timer"])
if _elapsed > 0:
    if UI.confirm_action(
            "↺  Reset", key="reset_clock", container=ctl[3],
            warning=f"Reset the match clock? It reads "
                    f"{control.fmt_clock(_elapsed)} and cannot be recovered. "
                    f"Events and notes are kept.",
            confirm_label="Reset the clock"):
        control.save_control(control.timer_reset(state))
        st.rerun()
elif ctl[3].button("↺  Reset", width="stretch"):
    control.save_control(control.timer_reset(state))
    st.rerun()

paused = state.get("paused", False)
if use_voice:
    rec_label = "● Resume mic" if paused else "● Pause mic"
    if ctl[4].button(rec_label, width="stretch",
                     type="primary" if paused else "secondary"):
        state["paused"] = not paused
        control.save_control(state)
        st.rerun()
else:
    ctl[4].caption("")

st.write("")

# --------------------------------------------------------------------------- #
# The Eye — the primary ingest, front and centre
# --------------------------------------------------------------------------- #
if use_vision:
    st.markdown(brand.section("The Eye", "VISION"), unsafe_allow_html=True)
    UI.render_eye_controls(state)
    UI.live_fragment(UI.render_eye_frame)
    st.caption("The Eye runs as its own process — it keeps analysing wherever "
               "you navigate, and closing this page does not stop it. Open "
               "**Live Eye** for a larger view.")
    st.write("")

# --------------------------------------------------------------------------- #
# Voice — the backup lane, only when this match uses it
# --------------------------------------------------------------------------- #
if use_voice:
    st.markdown(brand.section("Voice", "BACKUP"), unsafe_allow_html=True)
    st.caption("Recording paused — new events are not logged." if paused
               else "Narrate the calls the Eye can't make: fouls, cards, subs.")

    UI.render_voice_guide()

    undo_col, _ = st.columns([1, 4])
    if events and undo_col.button("Undo last event", width="stretch"):
        removed = S.pop_last_event()
        if removed:
            kind = removed.get("action") or "event"
            st.toast(f"Removed: {kind} ({removed.get('team') or 'unknown team'})")

    st.write("")

# --------------------------------------------------------------------------- #
# Match notes — always available, whatever the ingest mode.
#
# Notes are the one input that is never automated: neither the Eye nor the mic
# can supply your read of the game. Typing is the reliable path, so the composer
# is always here; speaking into it is the extra when voice is on.
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Match notes", "NOTES"), unsafe_allow_html=True)

if use_voice:
    write_tab, speak_tab = st.tabs(["Write a note", "Speak a note"])
    with write_tab:
        UI.render_note_composer(state)
    with speak_tab:
        thoughts_on = state.get("thoughts_mode", False)
        th1, th2 = st.columns([1, 2.4], vertical_alignment="center")
        if th1.button("● Stop recording" if thoughts_on else "Record thoughts",
                      type="primary" if thoughts_on else "secondary",
                      width="stretch", key="thoughts_toggle"):
            state["thoughts_mode"] = not thoughts_on
            control.save_control(state)
            st.rerun()
        with th2:
            if thoughts_on:
                st.caption("Recording — speak your thoughts freely. Each phrase "
                           "is saved as a note below (match events are paused). "
                           "Click Stop when done.")
            else:
                st.caption("Click, then speak a free-form synopsis or "
                           "observation. Your words are saved as timestamped "
                           "notes instead of match events.")
else:
    UI.render_note_composer(state)

st.write("")
UI.render_notes_list()
st.write("")

if not use_voice:
    st.caption("Voice is off for this match. Need to log a match *event* the Eye "
               "can't see? Use **Manual Entry**, or switch on voice under "
               "**Camera & Feed**.")
    st.write("")

# ---- Live stats + feed ---------------------------------------------------- #
UI.live_fragment(UI.render_stats_feed)
