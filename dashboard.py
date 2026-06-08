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
    color = HOME if team == "Home" else AWAY if team == "Away" else "#5b6e92"
    return f"<span class='chip' style='background:{color}'>{team or '—'}</span>"


def diverging_bar(h, a, show_pct=False) -> str:
    """Two-segment home/away bar sized by share of (h + a)."""
    h = h or 0
    a = a or 0
    total = h + a
    hp = (h / total * 100) if total else 0
    ap = (a / total * 100) if total else 0
    ht = f"{round(hp)}%" if show_pct else ""
    at = f"{round(ap)}%" if show_pct else ""
    hseg = f"<div class='seg home' style='width:{hp:.1f}%'>{ht}</div>" if hp else ""
    aseg = f"<div class='seg away' style='width:{ap:.1f}%'>{at}</div>" if ap else ""
    return f"<div class='kp-bar'>{hseg}{aseg}</div>"


def h2h_row(label, h, a, suffix="") -> str:
    return (
        f"<div class='h2h'><div class='h2h-top'>"
        f"<span class='n home'>{h}{suffix}</span>"
        f"<span class='lbl'>{label}</span>"
        f"<span class='n away'>{a}{suffix}</span></div>"
        f"{diverging_bar(h, a)}</div>"
    )


def ai_summary(events):
    """Ask the local model to write a short, neutral match summary."""
    home = S.team_stats(events, "Home")
    away = S.team_stats(events, "Away")
    hp, ap = S.possession(home, away)
    facts = (
        f"Final score: Home {home['Goals']} - {away['Goals']} Away. "
        f"Shots {home['Shots']}-{away['Shots']} (on target "
        f"{home['On Target']}-{away['On Target']}). Possession {hp}%-{ap}%. "
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
    hp, ap = S.possession(home, away)

    added_html = f"<span class='added'> {added}</span>" if added else ""
    half_lbl = half + ("  ·  ADDED TIME" if added else "")
    st.markdown(
        f"<div class='kp-card kp-board'>"
        f"<div class='side'><div class='team home'>Home</div>"
        f"<div class='sc home'>{home['Goals']}</div></div>"
        f"<div class='center'>"
        f"<div class='kp-half'>{half_lbl}</div>"
        f"<div class='kp-clock'>{main_clk}{added_html}</div>"
        f"<div style='margin-top:16px'>{diverging_bar(hp, ap, show_pct=True)}"
        f"<div class='kp-cap'>Possession</div></div>"
        f"</div>"
        f"<div class='side'><div class='team away'>Away</div>"
        f"<div class='sc away'>{away['Goals']}</div></div>"
        f"</div>",
        unsafe_allow_html=True)


def render_stats_feed():
    events = S.load_events()
    home = S.team_stats(events, "Home")
    away = S.team_stats(events, "Away")
    players = S.player_stats(events)

    col_stats, col_feed = st.columns([1.05, 1], gap="large")

    # ---- Team comparison (head-to-head) -------------------------------- #
    with col_stats:
        st.markdown(brand.section("Team comparison"), unsafe_allow_html=True)
        rows = "".join(h2h_row(k, home[k], away[k]) for k in S.STAT_KEYS)
        rows += h2h_row("Pass accuracy", home["Pass %"], away["Pass %"], suffix="%")
        st.markdown(
            f"<div class='kp-card'>"
            f"<div class='h2h-top' style='margin-bottom:10px'>"
            f"<span class='n home' style='color:{HOME}'>HOME</span>"
            f"<span class='lbl' style='font-weight:800'>Stat</span>"
            f"<span class='n away' style='color:{AWAY}'>AWAY</span></div>"
            f"{rows}</div>",
            unsafe_allow_html=True)

    # ---- Live feed ----------------------------------------------------- #
    with col_feed:
        st.markdown(brand.section("Live feed"), unsafe_allow_html=True)
        if not events:
            st.info("No events yet. Start narrating the match into your mic.")
        else:
            for e in reversed(events[-20:]):
                st.markdown(
                    f"<div class='kp-feed'>{IC.badge_html(e, 32)}"
                    f"<div class='body'><div class='top'>{team_chip(e.get('team'))}"
                    f"<span class='t'>{event_time(e)}</span></div>"
                    f"<div class='sum'>{event_summary(e)}</div></div></div>",
                    unsafe_allow_html=True)

    # ---- Players ------------------------------------------------------- #
    st.write("")
    st.markdown(brand.section("Player stats"), unsafe_allow_html=True)
    if players:
        cols = ["Team"] + S.STAT_KEYS + ["Pass %"]
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
            keys = ["Goals", "Shots", "On Target", "Tackles", "Fouls",
                    "Yellow Cards", "Red Cards", "Passes"]
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
        st.markdown(brand.section("Substitutions"), unsafe_allow_html=True)
        for e in subs:
            st.markdown(
                f"<div class='kp-feed'>{IC.badge_html(e, 30)}"
                f"<div class='body'><div class='top'>{team_chip(e.get('team'))}"
                f"<span class='t'>{event_time(e)}</span></div>"
                f"<div class='sum'>{e.get('player') or 'unknown'} comes on</div>"
                f"</div></div>", unsafe_allow_html=True)

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

# ---- Top bar: logo + editable match title --------------------------------- #
logo_col, title_col = st.columns([1, 2.4], vertical_alignment="center")
with logo_col:
    st.markdown(
        f"<img class='kp-reveal' src='{brand.logo_data_uri('dark', 260)}' "
        f"style='width:100%; max-width:360px; display:block; animation-delay:.12s'/>",
        unsafe_allow_html=True)
with title_col:
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
    st.caption(f"Live match tracker · click the title to rename · "
               f"{len(events)} events logged")

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
# Post-match summary + export
# --------------------------------------------------------------------------- #
left, right = st.columns([3, 2], gap="large")

with left:
    st.markdown(brand.section("Post-match summary"), unsafe_allow_html=True)
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
    st.markdown(brand.section("Player spotlight"), unsafe_allow_html=True)
    names = sorted(players.keys())
    st.selectbox("Spotlight a player", ["—"] + names,
                 key="spotlight", label_visibility="collapsed")

    st.markdown(brand.section("Export report"), unsafe_allow_html=True)
    if st.button("⬇  Save & export report", type="primary", width="stretch"):
        try:
            main_clk, added, half = control.clock_label(state["timer"])
            clk = f"{main_clk}{(' ' + added) if added else ''} ({half})"
            paths = report.generate(events=events,
                                    summary=state.get("summary", ""), clock=clk,
                                    match_name=state.get("match_name", ""))
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
