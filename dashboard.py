#!/usr/bin/env python3
"""
Kickoff Pulse — The Display.

A real-time Streamlit dashboard that reads match_data.json (written by
audio_tracker.py): a hero scoreboard with a 90-minute clock, head-to-head team
stats, per-player stats, a live event feed, and post-match summary + export.

Run via:  streamlit run dashboard.py   (or use ./kickoff.sh / .\\kickoff.ps1)
"""

import os
import time

import pandas as pd
import requests
import streamlit as st

import brand
import control
import icons as IC
import report
import share_image
import stats as S

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

HOME, AWAY = brand.HOME, brand.AWAY
NAVY, PULSE, SIGNAL = brand.NAVY, brand.PULSE, brand.SIGNAL

st.set_page_config(page_title=brand.NAME, page_icon=brand.LOGO_TRANSPARENT,
                   layout="wide")
st.markdown(brand.app_css(), unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Small render helpers
# --------------------------------------------------------------------------- #
def mic_svg(active: bool) -> str:
    color = "#34d399" if active else "#5b6e92"
    glow = "filter:drop-shadow(0 0 6px rgba(52,211,153,.9))" if active else ""
    return (
        f"<svg width='18' height='18' viewBox='0 0 24 24' fill='none' "
        f"stroke='{color}' stroke-width='2' stroke-linecap='round' "
        f"stroke-linejoin='round' style='{glow}'>"
        f"<rect x='9' y='3' width='6' height='11' rx='3'/>"
        f"<path d='M5 11a7 7 0 0 0 14 0'/><path d='M12 18v3'/></svg>"
    )


def event_time(e):
    return e.get("match_time") or (e.get("timestamp", "")[11:19])


def event_summary(e):
    parts = [p for p in [
        e.get("action"), e.get("result"),
        (f"by {e['player']}" if e.get("player") else None),
        (f"@ {e['location']}" if e.get("location") else None),
    ] if p]
    return " · ".join(parts) if parts else f'“{e.get("raw_text", "")}”'


def team_chip(team) -> str:
    if team == "Home":
        return ("<span class='team-chip' style='color:var(--c-home2);"
                "border-color:rgba(30,123,255,.4);background:rgba(30,123,255,.12)'>HOME</span>")
    if team == "Away":
        return ("<span class='team-chip' style='color:#FF6B6B;"
                "border-color:rgba(220,38,38,.45);background:rgba(220,38,38,.12)'>AWAY</span>")
    return ("<span class='team-chip' style='color:var(--c-muted);"
            "border-color:var(--border);background:rgba(255,255,255,.05)'>—</span>")


def roster_df(lineups, team) -> pd.DataFrame:
    """A two-column (Number, Name) editor frame for a team's roster."""
    rows = [{"Number": str(p.get("number") or ""), "Name": str(p.get("name") or "")}
            for p in control.roster_for(lineups, team)]
    if not rows:
        rows = [{"Number": "", "Name": ""}]  # one empty row to type into
    return pd.DataFrame(rows, columns=["Number", "Name"])


def df_to_players(df) -> list:
    """Convert an edited roster frame back to [{number, name}], dropping blanks."""
    players = []
    for _, r in df.iterrows():
        num = str(r.get("Number") or "").strip()
        name = str(r.get("Name") or "").strip()
        if num or name:
            players.append({"number": num, "name": name})
    return players


def cmp_row(label: str, h, a) -> str:
    """Wireframe-style diverging comparison row: value | bar | value."""
    h = h or 0
    a = a or 0
    total = h + a
    hp = (h / total * 100) if total else 0
    ap = (a / total * 100) if total else 0
    return (
        f"<div class='cmp-row'>"
        f"<span class='cmp-val home'>{h}</span>"
        f"<div class='cmp-bars'>"
        f"<div class='cmp-left'><div class='cmp-fill home' style='width:{hp:.0f}%'></div></div>"
        f"<span class='cmp-mid'>{label}</span>"
        f"<div class='cmp-right'><div class='cmp-fill away' style='width:{ap:.0f}%'></div></div>"
        f"</div>"
        f"<span class='cmp-val away'>{a}</span>"
        f"</div>"
    )


def ai_summary(events):
    """Ask the local model to write a short, neutral match summary."""
    home = S.team_stats(events, "Home")
    away = S.team_stats(events, "Away")
    facts = (
        f"Final score: Home {home['Goals']} - {away['Goals']} Away. "
        f"Shots {home['Shots']}-{away['Shots']} (on target "
        f"{home['On Target']}-{away['On Target']}). "
        f"Fouls {home['Fouls']}-{away['Fouls']}. "
        f"Cards: Home {home['Yellow Cards']}Y/{home['Red Cards']}R, "
        f"Away {away['Yellow Cards']}Y/{away['Red Cards']}R. "
        f"Saves {home['Saves']}-{away['Saves']}. "
        f"Corners {home['Corners']}-{away['Corners']}."
    )
    payload = {
        "model": OLLAMA_MODEL, "stream": False, "options": {"temperature": 0.4},
        "messages": [
            {"role": "system", "content":
             "You are a concise soccer reporter. Write a neutral 2-4 sentence "
             "summary of the match from the stats given. Plain text, no markdown."},
            {"role": "user", "content": facts},
        ],
    }
    resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


# --------------------------------------------------------------------------- #
# Live fragments (auto-refresh every second)
# --------------------------------------------------------------------------- #
def render_status_chips():
    status = control.load_status()
    paused = control.load_control().get("paused", False)
    online = control.tracker_online(status)
    if not online:
        dot, label, active = "off", "Offline", False
    elif paused:
        dot, label, active = "paused", "Paused", False
    else:
        dot, label, active = "rec", "Recording", True

    rec = control.fmt_clock(control.record_seconds(status))
    session = (control.fmt_clock(time.time() - status["session_start"])
               if status.get("session_start") else "00:00")
    events_n = status.get("events", len(S.load_events()))
    heard = status.get("last_heard") or "—"

    st.markdown(
        f"<div class='kp-status'>"
        f"<div class='kp-chip'>{mic_svg(active)}<span class='dot {dot}'></span>"
        f"<span class='v'>{label}</span></div>"
        f"<div class='kp-chip'><span class='l'>Rec</span>"
        f"<span class='v mono'>{rec}</span></div>"
        f"<div class='kp-chip'><span class='l'>Session</span>"
        f"<span class='v mono'>{session}</span></div>"
        f"<div class='kp-chip'><span class='l'>Events</span>"
        f"<span class='v'>{events_n}</span></div>"
        f"<div class='kp-chip heard'><span class='l'>Heard</span>"
        f"<span class='kp-heard'>{heard}</span></div>"
        f"</div>",
        unsafe_allow_html=True)


def render_scoreboard():
    events = S.load_events()
    state = control.load_control()
    home = S.team_stats(events, "Home")
    away = S.team_stats(events, "Away")
    main_clk, added, half = control.clock_label(state["timer"])

    teams = state.get("teams", {})
    home_name = teams.get("home", {}).get("name", "").strip() or "Home"
    away_name = teams.get("away", {}).get("name", "").strip() or "Away"

    added_html = f"<span class='added'> {added}</span>" if added else ""
    half_lbl = (half + ("  ·  ADDED TIME" if added else "")).upper()
    st.markdown(
        f"<div class='panel scoreboard'>"
        f"<div class='sb-side sb-home'>"
        f"<div class='sb-team'>{home_name}</div>"
        f"<div class='sb-score'>{home['Goals']}</div>"
        f"</div>"
        f"<div class='sb-center'>"
        f"<div class='sb-half'>{half_lbl}</div>"
        f"<div class='sb-clock'>{main_clk}{added_html}</div>"
        f"</div>"
        f"<div class='sb-side sb-away'>"
        f"<div class='sb-team'>{away_name}</div>"
        f"<div class='sb-score'>{away['Goals']}</div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True)


def render_stats_feed():
    events = S.load_events()
    state = control.load_control()
    home = S.team_stats(events, "Home")
    away = S.team_stats(events, "Away")
    players = S.player_stats(events)

    teams = state.get("teams", {})
    home_label = teams.get("home", {}).get("name", "").strip().upper() or "HOME"
    away_label = teams.get("away", {}).get("name", "").strip().upper() or "AWAY"

    col_stats, col_feed = st.columns([1.05, 1], gap="large")

    # ---- Team comparison (head-to-head) -------------------------------- #
    with col_stats:
        st.markdown(brand.section("Team comparison", "TEAM STATS"), unsafe_allow_html=True)
        legend = (
            f"<div class='cmp-legend'>"
            f"<span><span class='cmp-dot home'></span>{home_label}</span>"
            f"<span><span class='cmp-dot away'></span>{away_label}</span>"
            f"</div>"
        )
        rows = "".join(cmp_row(k, home[k], away[k]) for k in S.STAT_KEYS)
        st.markdown(
            f"<div class='panel'>{legend}"
            f"<div class='cmp-rows'>{rows}</div>"
            f"</div>",
            unsafe_allow_html=True)

    # ---- Live feed ----------------------------------------------------- #
    with col_feed:
        st.markdown(brand.section("Live feed", "REAL-TIME"), unsafe_allow_html=True)
        if not events:
            st.info("No events yet. Start narrating the match into your mic.")
        else:
            feed_items = "".join(
                f"<div class='feed-item'>{IC.badge_html(e, 32)}"
                f"<div class='feed-body'>"
                f"<div class='feed-meta'>"
                f"<span class='feed-type'>{IC.KIND_LABEL.get(IC.event_kind(e), 'Event')}</span>"
                f"{team_chip(e.get('team'))}"
                f"<span class='feed-time'>{event_time(e)}</span>"
                f"</div>"
                f"<div class='feed-desc'>{event_summary(e)}</div>"
                f"</div></div>"
                for e in reversed(events[-20:])
            )
            st.markdown(f"<div class='panel' style='padding:12px'>"
                        f"<div class='feed-list'>{feed_items}</div></div>",
                        unsafe_allow_html=True)

    # ---- Players ------------------------------------------------------- #
    st.write("")
    st.markdown(brand.section("Player stats", "PER PLAYER"), unsafe_allow_html=True)
    if players:
        cols = ["Team"] + S.STAT_KEYS
        df = pd.DataFrame(
            {p: {c: v.get(c) for c in cols} for p, v in players.items()}).T
        df = df.reindex(columns=cols)
        df.index.name = "Player"
        df = df.sort_values(["Goals", "Shots"], ascending=False)
        st.dataframe(df, width="stretch")

        pick = st.session_state.get("spotlight")
        if pick and pick in players:
            p = players[pick]
            accent = HOME if p["Team"] == "Home" else AWAY
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
    else:
        st.caption("No player-tagged events yet. Say a name or number, e.g. "
                   "“number 6 with a tackle”.")

    # ---- Substitutions ------------------------------------------------- #
    subs = [e for e in events if e.get("action") == "substitution"]
    if subs:
        st.write("")
        st.markdown(brand.section("Substitutions", "SUBS"), unsafe_allow_html=True)
        sub_items = "".join(
            f"<div class='feed-item'>{IC.badge_html(e, 30)}"
            f"<div class='feed-body'>"
            f"<div class='feed-meta'>{team_chip(e.get('team'))}"
            f"<span class='feed-time'>{event_time(e)}</span></div>"
            f"<div class='feed-desc'>{e.get('player') or 'unknown'} comes on</div>"
            f"</div></div>"
            for e in subs
        )
        st.markdown(f"<div class='panel' style='padding:12px'>"
                    f"<div class='feed-list'>{sub_items}</div></div>",
                    unsafe_allow_html=True)

    with st.expander("Raw event log"):
        if events:
            st.dataframe(pd.DataFrame(events), width="stretch", height=280)
        else:
            st.write("Empty.")


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
events = S.load_events()
state = control.load_control()
players = S.player_stats(events)

# ---- Sidebar: team info --------------------------------------------------- #
with st.sidebar:
    st.markdown(brand.section("Team info"), unsafe_allow_html=True)
    _teams = state.get("teams", {"home": {"name": "", "lineup": ""},
                                  "away": {"name": "", "lineup": ""}})

    with st.expander("Home team", expanded=True):
        _home_name = st.text_input(
            "Team name", value=_teams.get("home", {}).get("name", ""),
            placeholder="e.g. Eagles", key="sidebar_home_name")
        _home_lineup = st.text_area(
            "Lineup", value=_teams.get("home", {}).get("lineup", ""),
            placeholder="#1 Goalkeeper\n#5 Defender\n#10 Captain\n...",
            height=160, key="sidebar_home_lineup")

    with st.expander("Away team", expanded=True):
        _away_name = st.text_input(
            "Team name", value=_teams.get("away", {}).get("name", ""),
            placeholder="e.g. Hawks", key="sidebar_away_name")
        _away_lineup = st.text_area(
            "Lineup", value=_teams.get("away", {}).get("lineup", ""),
            placeholder="#1 Goalkeeper\n#5 Defender\n#10 Captain\n...",
            height=160, key="sidebar_away_lineup")

    if st.button("Save team info", type="primary", use_container_width=True,
                 key="save_team_info"):
        state["teams"] = {
            "home": {"name": _home_name.strip(), "lineup": _home_lineup.strip()},
            "away": {"name": _away_name.strip(), "lineup": _away_lineup.strip()},
        }
        control.save_control(state)
        st.rerun()

# ---- Top bar: centered logo + editable match title ------------------------ #
st.markdown(
    f"<div style='text-align:center; margin:2px 0 6px'>"
    f"<img class='kp-reveal' src='{brand.logo_data_uri('dark', 300)}' "
    f"style='width:300px; max-width:78%; animation-delay:.12s'/></div>",
    unsafe_allow_html=True)

match_name = (state.get("match_name") or "").strip()
with st.popover(match_name or "✎  Name this match"):
    st.caption("Name this match / session")
    new_name = st.text_input(
        "Match name", value=match_name,
        placeholder="e.g. Eagles vs Hawks — Jun 7",
        label_visibility="collapsed", key="match_name_input")
    s1, s2 = st.columns(2)
    if s1.button("Save name", type="primary", width="stretch"):
        state["match_name"] = new_name.strip()
        control.save_control(state)
        st.rerun()
    if match_name and s2.button("Clear", width="stretch"):
        state["match_name"] = ""
        control.save_control(state)
        st.rerun()
st.markdown(
    f"<div style='text-align:center; color:#9fb6dd; font-size:.85rem; margin-top:2px'>"
    f"Live match tracker · click the title to rename · {len(events)} events logged"
    f"</div>", unsafe_allow_html=True)

st.write("")

# ---- Live status chips ---------------------------------------------------- #
if hasattr(st, "fragment"):
    st.fragment(run_every=1.0)(render_status_chips)()
else:
    render_status_chips()

st.write("")

# ---- Hero scoreboard ------------------------------------------------------ #
if hasattr(st, "fragment"):
    st.fragment(run_every=1.0)(render_scoreboard)()
else:
    render_scoreboard()

st.write("")

# ---- Controls (outside any fragment so interactions never get interrupted) - #
ctl = st.columns([1, 1, 1, 1, 1.4], vertical_alignment="bottom")
if ctl[0].button("▶  Start", width="stretch"):
    control.save_control(control.timer_start(state)); st.rerun()
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

undo_col, _ = st.columns([1, 4])
if events and undo_col.button("Undo last event", width="stretch"):
    removed = S.pop_last_event()
    if removed:
        kind = removed.get("action") or "event"
        st.toast(f"Removed: {kind} ({removed.get('team') or 'unknown team'})")

st.write("")

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
    st.fragment(run_every=1.0)(render_stats_feed)()
else:
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=2000, key="kickoff_refresh")
    except ImportError:
        pass
    render_stats_feed()

st.divider()

# --------------------------------------------------------------------------- #
# Lineups & formation (optional) — used by the tracker (brain) + the report
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Lineups & formation"), unsafe_allow_html=True)
lineups = state.get("lineups") or {}
with st.expander("Edit lineups, numbers & formation — the tracker uses these to "
                 "name players and pick the side"):
    st.caption("Enter each side's formation and roster (shirt number + name). "
               "The brain maps a spoken “number 6” to that player's name and "
               "team; the report lists both lineups.")
    fc1, fc2 = st.columns(2)
    home_formation = fc1.text_input(
        "Home formation", value=control.lineup_formation(lineups, "Home"),
        placeholder="e.g. 4-3-3", key="home_formation")
    away_formation = fc2.text_input(
        "Away formation", value=control.lineup_formation(lineups, "Away"),
        placeholder="e.g. 4-4-2", key="away_formation")
    colcfg = {
        "Number": st.column_config.TextColumn("No.", width="small"),
        "Name": st.column_config.TextColumn("Name"),
    }
    ec1, ec2 = st.columns(2)
    home_roster = ec1.data_editor(
        roster_df(lineups, "Home"), num_rows="dynamic", width="stretch",
        hide_index=True, column_config=colcfg, key="home_roster")
    away_roster = ec2.data_editor(
        roster_df(lineups, "Away"), num_rows="dynamic", width="stretch",
        hide_index=True, column_config=colcfg, key="away_roster")
    if st.button("Save lineups", type="primary", width="stretch"):
        state["lineups"] = {
            "Home": {"formation": home_formation.strip(),
                     "players": df_to_players(home_roster)},
            "Away": {"formation": away_formation.strip(),
                     "players": df_to_players(away_roster)},
        }
        control.save_control(state)
        st.success("Lineups saved — the tracker now uses them for new events.")

st.write("")

# --------------------------------------------------------------------------- #
# Post-match summary + export
# --------------------------------------------------------------------------- #
left, right = st.columns([3, 2], gap="large")

with left:
    st.markdown(brand.section("Post-match summary", "AFTER MATCH"), unsafe_allow_html=True)
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
                drafted = ai_summary(events)
            state["summary"] = drafted
            control.save_control(state)
            st.rerun()
        except Exception as exc:
            st.error(f"Could not reach Ollama: {exc}")

with right:
    st.markdown(brand.section("Player spotlight", "SPOTLIGHT"), unsafe_allow_html=True)
    names = sorted(players.keys())
    st.selectbox("Spotlight a player", ["—"] + names,
                 key="spotlight", label_visibility="collapsed")

    st.markdown(brand.section("Export report", "EXPORT"), unsafe_allow_html=True)
    if st.button("Share card", width="stretch"):
        try:
            import share_image
            main_clk, added, half = control.clock_label(state["timer"])
            clk = f"{main_clk}{(' ' + added) if added else ''} ({half})"
            home_s = S.team_stats(events, "Home")
            away_s = S.team_stats(events, "Away")
            score = (home_s["Goals"], away_s["Goals"])
            card_bytes = share_image.render_to_bytes(
                events, score=score, clock=clk,
                match_name=state.get("match_name", ""))
            st.session_state["share_card_bytes"] = card_bytes
        except Exception as exc:
            st.error(f"Share card failed: {exc}")

    if st.session_state.get("share_card_bytes"):
        st.download_button(
            "Download share card (PNG)",
            data=st.session_state["share_card_bytes"],
            file_name="match_summary.png",
            mime="image/png",
            width="stretch",
        )

    if st.button("⬇  Save & export report", type="primary", width="stretch"):
        try:
            main_clk, added, half = control.clock_label(state["timer"])
            clk = f"{main_clk}{(' ' + added) if added else ''} ({half})"
            paths = report.generate(events=events,
                                    summary=state.get("summary", ""), clock=clk,
                                    match_name=state.get("match_name", ""),
                                    lineups=state.get("lineups"))
            st.session_state["report_paths"] = paths
            st.success(f"Report generated · {paths['events']} events")
        except Exception as exc:
            st.error(f"Export failed: {exc}")

    paths = st.session_state.get("report_paths")
    if paths:
        with open(paths["txt"], "rb") as fh:
            st.download_button("Download .txt", fh.read(),
                               file_name=os.path.basename(paths["txt"]),
                               mime="text/plain", width="stretch")
        with open(paths["pdf"], "rb") as fh:
            st.download_button("Download .pdf", fh.read(),
                               file_name=os.path.basename(paths["pdf"]),
                               mime="application/pdf", width="stretch")
        st.caption(f"Saved to {os.path.dirname(paths['pdf'])}/")

    # Mobile share card — a portrait summary image sized for texting.
    st.markdown(brand.section("Share image (mobile)"), unsafe_allow_html=True)
    if st.button("Generate share image", width="stretch"):
        try:
            main_clk, added, half = control.clock_label(state["timer"])
            clk = f"{main_clk}{(' ' + added) if added else ''} ({half})"
            st.session_state["share_png"] = share_image.render_to_bytes(
                events, clock=clk, match_name=state.get("match_name", ""))
        except Exception as exc:
            st.error(f"Could not build image: {exc}")
    share_png = st.session_state.get("share_png")
    if share_png:
        st.image(share_png, width="stretch")
        st.download_button(
            "Download image (.png)", share_png,
            file_name=f"kickoff_summary_{time.strftime('%Y%m%d_%H%M%S')}.png",
            mime="image/png", width="stretch")
        st.caption("Portrait card sized for texting. On your phone, tap and hold "
                   "to save or share it.")
