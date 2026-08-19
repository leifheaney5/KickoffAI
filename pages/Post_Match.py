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

UI.page_setup("AFTER MATCH", "Post-Match")

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
        st.rerun()
    except Exception as exc:
        st.error(f"Could not archive: {exc}")

st.write("")

# --------------------------------------------------------------------------- #
# Start the next match
#
# The working files describe exactly one match. Without this, a second match
# appends to the first and the two silently merge — which is what used to
# happen. Guarded, because it is the only destructive action in the app.
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Start the next match", "NEW MATCH"),
            unsafe_allow_html=True)

archived = control.is_archived(state)
unsaved = control.has_unsaved_work(state, events=events)

if archived:
    st.success("This match is saved to the library — starting a new one is safe.")
elif unsaved:
    st.warning("This match has **not** been saved to the library. Starting a new "
               "match clears the event log, notes and camera stats for good.")
else:
    st.caption("Nothing recorded for this match yet.")

nm1, nm2 = st.columns([1, 2.4], vertical_alignment="center")
keep = nm2.checkbox("Keep team names, lineups and camera feed", value=True,
                    help="Carries the setup you would otherwise retype every "
                         "week into the new match.")
confirm_needed = unsaved and not archived
if confirm_needed:
    confirmed = nm2.checkbox("I understand this match will be discarded",
                            key="new_match_confirm")
else:
    confirmed = True

if nm1.button("Start new match", type="primary", width="stretch",
              disabled=not confirmed):
    fresh = control.new_match(state, keep_teams=keep, keep_feed=keep)
    for k in ("report_paths", "share_png", "spotlight"):
        st.session_state.pop(k, None)
    st.toast(f"New match started ({fresh['match_id'][:8]}).")
    st.rerun()

st.caption(f"Current match id: `{state.get('match_id', '')[:8] or '—'}`")

st.write("")

# --------------------------------------------------------------------------- #
# Clips — cut the moments out of the match video
#
# Alignment is by wall clock, not the match clock: the match clock stops at
# half-time while the video keeps rolling, so mapping match time onto video time
# puts every second-half event minutes early.
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Clips", "VIDEO"), unsafe_allow_html=True)

import clips as CL  # noqa: E402
import screen_recorder  # noqa: E402

if not CL.ffmpeg_available():
    st.caption("Clipping needs ffmpeg (`brew install ffmpeg`).")
else:
    clip_video = st.text_input(
        "Match video", value=st.session_state.get("kp_clip_video", ""),
        placeholder="recordings/20260819-match.mp4", key="kp_clip_video_in",
        help="One file covering the whole match, including half-time.")

    anchor = None
    if clip_video and os.path.exists(clip_video):
        # If the app recorded it, alignment is already known exactly.
        auto = next((r for r in screen_recorder.list_recordings()
                     if r["path"] == clip_video), None)
        rec_state = screen_recorder.status()
        started = None
        if auto:
            started = auto["mtime"] - (CL.probe_duration(clip_video) or 0)
        if started:
            anchor = CL.anchor_from_recording(started)
            st.caption("Aligned automatically — this video was recorded by the app.")
        else:
            st.caption("Point at one moment you can find in the video and "
                       "everything else follows from it.")
            clipworthy = [e for e in events if CL.is_clipworthy(e)]
            if not clipworthy:
                st.info("No goals, cards or shots on target logged, so there is "
                        "nothing to clip yet.")
            else:
                ac1, ac2 = st.columns([2, 1])
                pick = ac1.selectbox(
                    "A moment you can see in the video", clipworthy,
                    format_func=lambda e: f"{e.get('match_time','')} · "
                                          f"{CL.clip_window(e)[0]} · "
                                          f"{e.get('team','')}")
                at_min = ac2.number_input("is at (minutes into the video)",
                                          0.0, 300.0, 0.0, 0.5)
                anchor = CL.anchor_from_event(pick, at_min * 60)

    if anchor and clip_video and os.path.exists(clip_video):
        duration = CL.probe_duration(clip_video)
        plan = CL.plan_clips(events, anchor, duration=duration)
        usable = [c for c in plan if c["ok"]]
        st.caption(f"{len(usable)} clip(s) to cut"
                   + (f" · {len(plan) - len(usable)} outside the video"
                      if len(plan) > len(usable) else ""))
        if plan:
            st.dataframe(
                [{"Match time": c["match_time"], "Moment": c["label"],
                  "Team": c["team"], "Player": c["player"],
                  "Video at": f"{c['start'] // 60:.0f}:{c['start'] % 60:04.1f}",
                  "OK": "yes" if c["ok"] else c["why"]} for c in plan],
                width="stretch", hide_index=True)

        if st.button("Cut clips", type="primary", width="stretch",
                     disabled=not usable):
            bar = st.progress(0.0, text="Cutting…")
            res = CL.extract(plan, clip_video,
                             os.path.join("exports", "clips"),
                             progress=lambda f, lbl: bar.progress(f, text=lbl))
            bar.progress(1.0, text="Done")
            st.session_state["kp_clips"] = res
            st.session_state["kp_clip_video"] = clip_video
            st.success(f"Cut {len(res['clips'])} clip(s).")
            for f in res["failed"][:3]:
                st.warning(f"{f['name']}: could not cut")
            st.rerun()

made = st.session_state.get("kp_clips")
if made and made.get("clips"):
    st.caption(f"{len(made['clips'])} clip(s) in exports/clips/")
    for c in made["clips"][:6]:
        st.markdown(f"**{c['match_time']} · {c['label']}** "
                    f"{c['team']} {c['player']}")
        st.video(c["path"])

st.write("")

# --------------------------------------------------------------------------- #
# Player packs — what you actually hand to a player or parent
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Player pack", "SHARE"), unsafe_allow_html=True)
st.caption("One player's own line, their clips and their season trend, in a "
           "form a parent will open. Contains only that player.")

import player_pack as PP  # noqa: E402

pp_names = sorted(players.keys())
if not pp_names:
    st.caption("No player-attributed events yet.")
else:
    pk1, pk2 = st.columns([2, 1], vertical_alignment="bottom")
    who = pk1.selectbox("Player", pp_names, key="pack_player")
    if pk2.button("Build pack", type="primary", width="stretch"):
        try:
            pack = PP.build_pack(
                who, events, clip_results=st.session_state.get("kp_clips"),
                match_name=state.get("match_name", ""), clock=_match_clock())
            st.session_state["kp_pack"] = pack
        except Exception as exc:
            st.error(f"Could not build the pack: {exc}")

    pack = st.session_state.get("kp_pack")
    if pack:
        pc1, pc2 = st.columns([1, 1])
        pc1.image(pack["card_bytes"], width="stretch")
        with pc2:
            st.caption(f"{len(pack['clips'])} clip(s) included.")
            with open(pack["path"], "rb") as fh:
                st.download_button("Download pack (.zip)", fh.read(),
                                   file_name=os.path.basename(pack["path"]),
                                   mime="application/zip", width="stretch")
            st.download_button("Just the card (.png)", pack["card_bytes"],
                               file_name=f"{who.replace('#', '')}_card.png",
                               mime="image/png", width="stretch")

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
