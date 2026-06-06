#!/usr/bin/env python3
"""
KickoffAI — The Display.

A clean, real-time Streamlit dashboard that reads match_data.json (written by
audio_tracker.py) and shows: a 90-minute match clock with halftime / added-time,
a live event feed, aggregate team stats, per-player stats and spotlight cards,
substitutions, and a possession estimate. Includes controls to pause recording,
record a post-match summary, and export an email-friendly report (txt + pdf).

Run via:  streamlit run dashboard.py   (or use ./kickoff.sh)
"""

import os

import pandas as pd
import requests
import streamlit as st

import control
import report
import stats as S

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

HOME = "#2563eb"   # blue
AWAY = "#dc2626"   # red

st.set_page_config(page_title="KickoffAI", page_icon=None, layout="wide")

# --------------------------------------------------------------------------- #
# Styling — minimal, neutral, sleek
# --------------------------------------------------------------------------- #
st.markdown(
    f"""
    <style>
      .block-container {{ padding-top: 1.6rem; max-width: 1200px; }}
      h1, h2, h3, h4 {{ font-weight: 700; letter-spacing: -0.01em; }}
      .clock {{
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 3.4rem; font-weight: 800; line-height: 1; text-align: center;
      }}
      .clock-added {{ color: {AWAY}; font-size: 1.4rem; font-weight: 700; }}
      .clock-half {{ text-align:center; color:#6b7280; font-weight:600;
                     letter-spacing:.12em; text-transform:uppercase;
                     font-size:.8rem; }}
      .score {{ font-size: 3rem; font-weight: 800; line-height: 1; }}
      .card {{ border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px 18px;
               background: #ffffff; }}
      .card.home {{ border-top: 4px solid {HOME}; }}
      .card.away {{ border-top: 4px solid {AWAY}; }}
      .card-title {{ font-weight: 700; font-size: 1.05rem; margin-bottom: 8px; }}
      .row {{ display:flex; justify-content:space-between; padding: 4px 0;
              border-bottom: 1px solid #f1f3f5; font-size: .96rem; }}
      .row:last-child {{ border-bottom: none; }}
      .row .v {{ font-weight: 700; }}
      .feed {{ padding: 7px 12px; border-radius: 8px; margin-bottom: 6px;
               background: #f8f9fa; font-size: .95rem; }}
      .tag {{ display:inline-block; min-width:46px; text-align:center;
              padding: 1px 8px; border-radius: 6px; font-size: .76rem;
              font-weight: 700; color: white; }}
      .t {{ color:#9ca3af; font-variant-numeric: tabular-nums; margin: 0 8px; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def event_time(e):
    return e.get("match_time") or (e.get("timestamp", "")[11:19])


def event_summary(e):
    parts = [p for p in [
        e.get("action"), e.get("result"),
        (f"by {e['player']}" if e.get("player") else None),
        (f"@ {e['location']}" if e.get("location") else None),
    ] if p]
    return " / ".join(parts) if parts else f'"{e.get("raw_text", "")}"'


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
# Load current state
# --------------------------------------------------------------------------- #
events = S.load_events()
state = control.load_control()
home = S.team_stats(events, "Home")
away = S.team_stats(events, "Away")
players = S.player_stats(events)

st.markdown("# KickoffAI")
st.caption(f"Live match tracker · {len(events)} events logged")

# --------------------------------------------------------------------------- #
# CONTROLS  (outside the auto-refresh fragment so they never reset)
# --------------------------------------------------------------------------- #
with st.container():
    c1, c2 = st.columns([3, 2])

    with c1:
        st.markdown("##### Match clock")
        b1, b2, b3, b4 = st.columns(4)
        if b1.button("Start", use_container_width=True):
            control.save_control(control.timer_start(state))
            st.rerun()
        if b2.button("Pause", use_container_width=True):
            control.save_control(control.timer_pause(state))
            st.rerun()
        if b3.button("Halftime", use_container_width=True):
            control.save_control(control.timer_halftime(state))
            st.rerun()
        if b4.button("Reset", use_container_width=True):
            control.save_control(control.timer_reset(state))
            st.rerun()

    with c2:
        st.markdown("##### Recording")
        paused = state.get("paused", False)
        label = "Resume recording" if paused else "Pause recording"
        if st.button(label, use_container_width=True, type="secondary"):
            state["paused"] = not paused
            control.save_control(state)
            st.rerun()
        st.caption("Paused — new events are not logged." if paused
                   else "Recording — narrate the match into your mic.")

st.divider()

# --------------------------------------------------------------------------- #
# LIVE DISPLAY  (auto-updating)
# --------------------------------------------------------------------------- #
def render_live():
    events = S.load_events()
    state = control.load_control()
    home = S.team_stats(events, "Home")
    away = S.team_stats(events, "Away")
    players = S.player_stats(events)
    main_clk, added, half = control.clock_label(state["timer"])
    hp, ap = S.possession(home, away)

    # Clock + scoreboard
    sc1, sc2, sc3 = st.columns([2, 3, 2])
    with sc1:
        st.markdown(
            f"<div style='text-align:right'><div class='card-title' "
            f"style='color:{HOME}'>HOME</div>"
            f"<div class='score' style='color:{HOME}'>{home['Goals']}</div></div>",
            unsafe_allow_html=True)
    with sc2:
        st.markdown(
            f"<div class='clock-half'>{half}{'  ·  added time' if added else ''}</div>"
            f"<div class='clock'>{main_clk}"
            f"<span class='clock-added'> {added}</span></div>",
            unsafe_allow_html=True)
    with sc3:
        st.markdown(
            f"<div><div class='card-title' style='color:{AWAY}'>AWAY</div>"
            f"<div class='score' style='color:{AWAY}'>{away['Goals']}</div></div>",
            unsafe_allow_html=True)

    # Possession
    st.markdown("###### Possession")
    st.markdown(
        f"<div style='display:flex;height:24px;border-radius:7px;overflow:hidden;"
        f"font-weight:700;color:white;font-size:.82rem'>"
        f"<div style='width:{hp}%;background:{HOME};line-height:24px;"
        f"padding-left:8px'>{hp}%</div>"
        f"<div style='width:{ap}%;background:{AWAY};line-height:24px;"
        f"text-align:right;padding-right:8px'>{ap}%</div></div>",
        unsafe_allow_html=True)

    st.write("")

    # Team stat cards
    def stat_card(col, team, css, data):
        rows = "".join(
            f"<div class='row'><span>{k}</span><span class='v'>{data[k]}</span></div>"
            for k in S.STAT_KEYS
        )
        rows += (f"<div class='row'><span>Pass accuracy</span>"
                 f"<span class='v'>{data['Pass %']}%</span></div>")
        col.markdown(
            f"<div class='card {css}'><div class='card-title'>{team}</div>"
            f"{rows}</div>", unsafe_allow_html=True)

    cc1, cc2 = st.columns(2)
    stat_card(cc1, "Home", "home", home)
    stat_card(cc2, "Away", "away", away)

    st.write("")

    # Player stats
    st.markdown("#### Player stats")
    if players:
        cols = ["Team"] + S.STAT_KEYS + ["Pass %"]
        df = pd.DataFrame(
            {p: {c: v.get(c) for c in cols} for p, v in players.items()}
        ).T
        df = df.reindex(columns=cols)
        df.index.name = "Player"
        df = df.sort_values(["Goals", "Shots"], ascending=False)
        st.dataframe(df, use_container_width=True)

        # Spotlight card for the player picked in the controls
        pick = st.session_state.get("spotlight")
        if pick and pick in players:
            p = players[pick]
            accent = HOME if p["Team"] == "Home" else AWAY
            keys = ["Goals", "Shots", "On Target", "Tackles", "Fouls",
                    "Yellow Cards", "Red Cards", "Passes"]
            rows = "".join(
                f"<div class='row'><span>{k}</span><span class='v'>{p[k]}</span></div>"
                for k in keys)
            st.markdown(
                f"<div class='card' style='border-top:4px solid {accent}'>"
                f"<div class='card-title'>{pick} "
                f"<span style='color:{accent}'>· {p['Team'] or '—'}</span></div>"
                f"{rows}</div>", unsafe_allow_html=True)
    else:
        st.caption("No player-tagged events yet. Say a name or number, e.g. "
                   "“number 6 with a tackle”.")

    st.write("")

    # Substitutions
    subs = [e for e in events if e.get("action") == "substitution"]
    if subs:
        st.markdown("#### Substitutions")
        for e in subs:
            color = HOME if e.get("team") == "Home" else AWAY
            st.markdown(
                f"<div class='feed'><span class='tag' style='background:{color}'>"
                f"{e.get('team') or '—'}</span><span class='t'>{event_time(e)}</span>"
                f"{e.get('player') or 'unknown'} on</div>", unsafe_allow_html=True)
        st.write("")

    # Live feed
    st.markdown("#### Live feed")
    if not events:
        st.info("No events yet. Start narrating the match into your mic.")
    else:
        for e in reversed(events[-25:]):
            team = e.get("team")
            color = HOME if team == "Home" else AWAY if team == "Away" else "#6b7280"
            st.markdown(
                f"<div class='feed'><span class='tag' style='background:{color}'>"
                f"{team or '—'}</span><span class='t'>{event_time(e)}</span>"
                f"{event_summary(e)}</div>", unsafe_allow_html=True)

    with st.expander("Raw event log"):
        if events:
            st.dataframe(pd.DataFrame(events), use_container_width=True, height=280)
        else:
            st.write("Empty.")


# Auto-refresh just the live display so the controls/notes never get interrupted.
if hasattr(st, "fragment"):
    live = st.fragment(run_every=1.0)(render_live)
    live()
else:  # fallback for older Streamlit
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=2000, key="kickoff_refresh")
    except ImportError:
        pass
    render_live()

st.divider()

# --------------------------------------------------------------------------- #
# POST-MATCH SUMMARY + EXPORT  (outside the fragment)
# --------------------------------------------------------------------------- #
left, right = st.columns([3, 2])

with left:
    st.markdown("#### Post-match summary")
    notes = st.text_area(
        "Summary / notes", value=state.get("summary", ""),
        height=140, label_visibility="collapsed",
        placeholder="Type a summary, or generate one from the stats…")
    a, b = st.columns(2)
    if a.button("Save summary", use_container_width=True):
        state["summary"] = notes
        control.save_control(state)
        st.success("Saved.")
    if b.button("Draft with AI", use_container_width=True):
        try:
            with st.spinner("Writing summary…"):
                drafted = ai_summary(events)
            state["summary"] = drafted
            control.save_control(state)
            st.rerun()
        except Exception as exc:
            st.error(f"Could not reach Ollama: {exc}")

with right:
    st.markdown("#### Player spotlight")
    names = sorted(players.keys())
    st.selectbox("Spotlight a player", ["—"] + names,
                 key="spotlight", label_visibility="collapsed")

    st.markdown("#### Export report")
    if st.button("Save & export report", type="primary",
                 use_container_width=True):
        try:
            main_clk, added, half = control.clock_label(state["timer"])
            clk = f"{main_clk}{(' ' + added) if added else ''} ({half})"
            paths = report.generate(events=events,
                                    summary=state.get("summary", ""), clock=clk)
            st.session_state["report_paths"] = paths
            st.success(f"Report generated · {paths['events']} events")
        except Exception as exc:
            st.error(f"Export failed: {exc}")

    paths = st.session_state.get("report_paths")
    if paths:
        with open(paths["txt"], "rb") as fh:
            st.download_button("Download .txt", fh.read(),
                               file_name=os.path.basename(paths["txt"]),
                               mime="text/plain", use_container_width=True)
        with open(paths["pdf"], "rb") as fh:
            st.download_button("Download .pdf", fh.read(),
                               file_name=os.path.basename(paths["pdf"]),
                               mime="application/pdf", use_container_width=True)
        st.caption(f"Saved to {os.path.dirname(paths['pdf'])}/")
