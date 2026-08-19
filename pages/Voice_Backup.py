#!/usr/bin/env python3
"""
Voice Backup — tune what the tracker hears.

Vision is the primary ingest; this page is the backup lane. Reach for it when
there is no camera to point at, when a feed drops mid-match, or to narrate the
calls the Eye cannot make — fouls, cards, substitutions, your own read of the
game.

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

UI.page_setup("SET UP", "Voice Backup")

state = control.load_control()

# Say plainly whether any of this is live for the current match — these dials do
# nothing at all in vision-only mode, and silently ineffective controls are the
# most confusing kind.
if not control.uses_voice(state):
    st.info("Voice is off for this match, so nothing here is active. Switch the "
            "ingest mode to **Vision + voice notes** or **Voice only** on "
            "Camera & Feed to use the mic.")
else:
    st.caption(f"Active · ingest mode is "
               f"**{control.INGEST_LABELS[state['ingest_mode']]}**.")

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
    usage = screen_recorder.disk_usage()
    if recs:
        with st.expander(f"Recordings ({len(recs)} · {usage['gb']:.1f} GB)"):
            # Recordings are the fastest-growing thing the app writes, and a full
            # disk ends a live capture. Surface it before that happens.
            du1, du2 = st.columns(2)
            du1.metric("Recordings", f"{usage['gb']:.1f} GB")
            du2.metric("Free on disk", f"{usage['free_gb']:.0f} GB")
            if usage["free_gb"] < 10:
                st.error("Less than 10 GB free — a long capture may run out of "
                         "space mid-match.")

            plan = screen_recorder.prune_recordings(dry_run=True)
            if plan["count"]:
                st.caption(
                    f"Retention: keep {screen_recorder.KEEP_DAYS:.0f} days / "
                    f"{screen_recorder.MAX_GB:.0f} GB. "
                    f"{plan['count']} file(s) are over the limit "
                    f"({plan['freed_gb']:.1f} GB).")
                if UI.confirm_action(
                        f"Delete {plan['count']} old recording(s)",
                        key="prune_recordings",
                        warning=f"Permanently delete {plan['count']} recording(s), "
                                f"freeing {plan['freed_gb']:.1f} GB? The video "
                                f"files cannot be recovered.",
                        confirm_label="Delete them"):
                    done = screen_recorder.prune_recordings()
                    st.toast(f"Freed {done['freed_gb']:.1f} GB.")
                    st.rerun()
            else:
                st.caption(f"Within the retention limit "
                           f"({screen_recorder.KEEP_DAYS:.0f} days / "
                           f"{screen_recorder.MAX_GB:.0f} GB).")

            st.divider()
            for r in recs[:12]:
                mb = r["size"] / (1024 * 1024)
                st.caption(f"{r['name']} · {mb:.0f} MB · {r['path']}")
