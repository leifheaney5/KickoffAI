#!/usr/bin/env python3
"""
Post-Match — wrap up and share.

The after-the-whistle workflow: write (or AI-draft) a summary, spotlight a
player, export the report + data files, archive the match to the library, and
build a portrait share card for texting.
"""

import os
import time

import streamlit as st

import brand
import control
import report
import share_image
import stats as S
import ui_helpers as UI

st.markdown(brand.app_css(), unsafe_allow_html=True)
st.markdown(brand.page_header("AFTER MATCH", "Post-Match"), unsafe_allow_html=True)

events = S.load_events()
state = control.load_control()
players = S.player_stats(events)


def _match_clock() -> str:
    main_clk, added, half = control.clock_label(state["timer"])
    return f"{main_clk}{(' ' + added) if added else ''} ({half})"


left, right = st.columns([3, 2], gap="large")

with left:
    st.markdown(brand.section("Post-match summary", "AFTER MATCH"),
                unsafe_allow_html=True)
    notes = st.text_area(
        "Summary / notes", value=state.get("summary", ""),
        height=150, label_visibility="collapsed",
        placeholder="Type a summary, or generate one from the stats…")
    a, b = st.columns(2)
    if a.button("Save summary", width="stretch"):
        state["summary"] = notes
        control.save_control(state)
        st.success("Saved.")
    if b.button("✦  Draft with AI", type="primary", width="stretch"):
        try:
            with st.spinner("Writing summary…"):
                drafted = UI.ai_summary(events)
            state["summary"] = drafted
            control.save_control(state)
            st.rerun()
        except Exception as exc:
            st.error(f"Could not reach Ollama: {exc}")

with right:
    st.markdown(brand.section("Player spotlight", "SPOTLIGHT"),
                unsafe_allow_html=True)
    names = sorted(players.keys())
    pick = st.selectbox("Spotlight a player", ["—"] + names,
                        key="spotlight", label_visibility="collapsed")
    if pick and pick in players:
        p = players[pick]
        accent = UI.HOME if p["Team"] == "Home" else UI.AWAY
        keys = ["Goals", "Shots", "On Target", "Saves", "Tackles", "Fouls",
                "Yellow Cards", "Red Cards"]
        chips = "".join(
            f"<div class='row'><span>{k}</span><span class='v'>{p[k]}</span></div>"
            for k in keys)
        st.markdown(
            f"<div class='kp-card' style='border-top:3px solid {accent};margin-top:10px'>"
            f"<div class='card-title'>{pick} "
            f"<span style='color:{accent}'>· {p['Team'] or '—'}</span></div>"
            f"{chips}</div>", unsafe_allow_html=True)

st.write("")

# ---- Export & data -------------------------------------------------------- #
st.markdown(brand.section("Export & data", "EXPORT"), unsafe_allow_html=True)
if st.button("⬇  Generate report & data", type="primary", width="stretch"):
    try:
        paths = report.generate(events=events,
                                summary=state.get("summary", ""),
                                clock=_match_clock(),
                                match_name=state.get("match_name", ""),
                                lineups=state.get("lineups"))
        st.session_state["report_paths"] = paths
        st.success(f"Generated · {paths['events']} events")
    except Exception as exc:
        st.error(f"Export failed: {exc}")

paths = st.session_state.get("report_paths")
if paths:
    # (label, key in paths, MIME) — only shown if the artifact exists.
    artifacts = [
        ("Report (.pdf)", "pdf", "application/pdf"),
        ("Report (.txt)", "txt", "text/plain"),
        ("Events (.csv)", "events_csv", "text/csv"),
        ("Team stats (.csv)", "team_csv", "text/csv"),
        ("Player stats (.csv)", "players_csv", "text/csv"),
        ("Raw data (.json)", "data", "application/json"),
        ("Timeline (.png)", "image", "image/png"),
    ]
    dcols = st.columns(2)
    i = 0
    for label, key, mime in artifacts:
        p = paths.get(key)
        if p and os.path.exists(p):
            with open(p, "rb") as fh:
                dcols[i % 2].download_button(
                    label, fh.read(), file_name=os.path.basename(p),
                    mime=mime, width="stretch", key=f"dl_{key}")
            i += 1
    st.caption(f"Saved to {os.path.dirname(paths['pdf'])}/")

st.write("")

# ---- Archive to the match library ----------------------------------------- #
st.markdown(brand.section("Archive to library"), unsafe_allow_html=True)
lib_video = st.text_input(
    "Match video to bundle (optional)", value="",
    placeholder="path/to/match.mp4", key="lib_video_path")
if st.button("Save match to library", width="stretch"):
    try:
        import finalize
        with st.spinner("Archiving match…"):
            slug = finalize.finalize_match(
                events=events, state=state, clock=_match_clock(),
                video_path=lib_video.strip() or None)
        st.success(f"Saved to library as “{slug}”. Open the Match Library "
                   "page to browse or export it.")
    except Exception as exc:
        st.error(f"Could not archive: {exc}")

st.write("")

# ---- Share card — portrait summary image for texting / social ------------- #
st.markdown(brand.section("Share card (mobile)"), unsafe_allow_html=True)
if st.button("Generate share card", width="stretch"):
    try:
        st.session_state["share_png"] = share_image.render_to_bytes(
            events, clock=_match_clock(),
            match_name=state.get("match_name", ""))
    except Exception as exc:
        st.error(f"Could not build image: {exc}")
share_png = st.session_state.get("share_png")
if share_png:
    st.image(share_png, width="stretch")
    st.download_button(
        "Download card (.png)", share_png,
        file_name=f"kickoff_summary_{time.strftime('%Y%m%d_%H%M%S')}.png",
        mime="image/png", width="stretch")
    st.caption("Portrait card sized for texting. On your phone, tap and hold "
               "to save or share it.")
