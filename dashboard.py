#!/usr/bin/env python3
"""
KickoffAI — The Display.

A real-time Streamlit dashboard that reads match_data.json (written by
audio_tracker.py) and shows a live event feed, aggregate team stats, and a
rough possession estimate. Auto-refreshes every couple of seconds.

Run via:  streamlit run dashboard.py
(or just use ./kickoff.sh)
"""

import json
import os
from datetime import datetime

import pandas as pd
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
    _HAS_AUTOREFRESH = True
except ImportError:
    _HAS_AUTOREFRESH = False

DATA_FILE = os.environ.get("KICKOFF_DATA_FILE", "match_data.json")

HOME_COLOR = "#2563eb"  # blue
AWAY_COLOR = "#dc2626"  # red

# "Successful" results used for the possession estimate.
POSITIVE_RESULTS = {
    "complete", "scored", "on target", "saved", "won",
    "successful", "blocked",  # a block is a successful defensive action
}

st.set_page_config(page_title="KickoffAI — Live Match", page_icon="⚽",
                   layout="wide")

# --------------------------------------------------------------------------- #
# Styling
# --------------------------------------------------------------------------- #
st.markdown(
    f"""
    <style>
      .block-container {{ padding-top: 2rem; }}
      .team-card {{
        border-radius: 14px; padding: 18px 22px; color: white;
        box-shadow: 0 4px 14px rgba(0,0,0,0.18);
      }}
      .home-card {{ background: linear-gradient(135deg, {HOME_COLOR}, #1e40af); }}
      .away-card {{ background: linear-gradient(135deg, {AWAY_COLOR}, #991b1b); }}
      .team-name {{ font-size: 1.4rem; font-weight: 700; letter-spacing: .5px; }}
      .stat-row {{ display:flex; justify-content:space-between;
                   font-size: 1.05rem; padding: 3px 0; }}
      .stat-val {{ font-weight: 700; }}
      .feed-line {{ padding: 8px 12px; border-radius: 8px; margin-bottom: 6px;
                    background: rgba(125,125,125,0.10); }}
      .badge {{ display:inline-block; padding:1px 9px; border-radius:999px;
                font-size:.78rem; font-weight:700; color:white; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Data loading + aggregation
# --------------------------------------------------------------------------- #
def load_events() -> list:
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        # File may be mid-write; skip this refresh tick.
        return []


def team_stats(events: list, team: str) -> dict:
    rows = [e for e in events if e.get("team") == team]
    actions = [e.get("action") for e in rows]

    def res(e):
        return (e.get("result") or "").lower()

    def is_on_target(e):
        return e.get("action") == "shot" and res(e) in {"on target", "scored", "saved"}

    def card(color):
        # Accept either action "card" + result color, or a "<color>_card" action.
        return sum(
            1 for e in rows
            if (e.get("action") == "card" and color in res(e))
            or e.get("action") == f"{color}_card"
        )

    passes = sum(1 for a in actions if a == "pass")
    passes_complete = sum(
        1 for e in rows if e.get("action") == "pass" and res(e) == "complete"
    )

    return {
        "Goals": sum(1 for e in rows if e.get("action") == "goal"
                     or res(e) == "scored"),
        "Shots": sum(1 for a in actions if a == "shot")
                 + sum(1 for e in rows if e.get("action") == "goal"),
        "On Target": sum(1 for e in rows if is_on_target(e))
                     + sum(1 for e in rows if e.get("action") == "goal"),
        "Saves": sum(1 for a in actions if a == "save"),
        "Tackles": sum(1 for a in actions if a == "tackle"),
        "Fouls": sum(1 for a in actions if a == "foul"),
        "🟨 Yellow": card("yellow"),
        "🟥 Red": card("red"),
        "Corners": sum(1 for a in actions if a == "corner"),
        "Offsides": sum(1 for a in actions if a == "offside"),
        "Passes": passes,
        "Pass %": round(100 * passes_complete / passes, 0) if passes else 0,
        "_successful": sum(
            1 for e in rows
            if res(e) in POSITIVE_RESULTS
            or e.get("action") in {"pass", "dribble", "cross"}
        ),
    }


def possession(home: dict, away: dict):
    h, a = home["_successful"], away["_successful"]
    total = h + a
    if total == 0:
        return 50.0, 50.0
    return round(100 * h / total, 1), round(100 * a / total, 1)


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
if _HAS_AUTOREFRESH:
    st_autorefresh(interval=2000, key="kickoff_refresh")

events = load_events()
home = team_stats(events, "Home")
away = team_stats(events, "Away")
home_pos, away_pos = possession(home, away)

st.markdown("## ⚽ KickoffAI — Live Match Tracker")
st.caption(
    f"Reading **{DATA_FILE}** · {len(events)} events logged · "
    f"updated {datetime.now().strftime('%H:%M:%S')}"
    + ("" if _HAS_AUTOREFRESH else
       "  ·  ⚠️ install `streamlit-autorefresh` for live updates")
)

# Scoreboard
score_col1, score_col2, score_col3 = st.columns([3, 2, 3])
with score_col1:
    st.markdown(
        f"<div class='team-card home-card'><div class='team-name'>🏠 HOME</div>"
        f"<div style='font-size:3rem;font-weight:800'>{home['Goals']}</div></div>",
        unsafe_allow_html=True)
with score_col2:
    st.markdown(
        "<div style='text-align:center;font-size:2rem;font-weight:700;"
        "padding-top:28px'>vs</div>", unsafe_allow_html=True)
with score_col3:
    st.markdown(
        f"<div class='team-card away-card' style='text-align:right'>"
        f"<div class='team-name'>AWAY ✈️</div>"
        f"<div style='font-size:3rem;font-weight:800'>{away['Goals']}</div></div>",
        unsafe_allow_html=True)

st.write("")

# Possession bar
st.markdown("#### Possession")
pos_bar = (
    f"<div style='display:flex;height:26px;border-radius:8px;overflow:hidden;"
    f"font-weight:700;color:white;font-size:.85rem'>"
    f"<div style='width:{home_pos}%;background:{HOME_COLOR};text-align:left;"
    f"padding-left:8px;line-height:26px'>{home_pos}%</div>"
    f"<div style='width:{away_pos}%;background:{AWAY_COLOR};text-align:right;"
    f"padding-right:8px;line-height:26px'>{away_pos}%</div></div>"
)
st.markdown(pos_bar, unsafe_allow_html=True)
st.caption("Estimated from each team's share of successful actions "
           "(passes, dribbles, crosses, and other positive outcomes).")

st.write("")

# Stat cards
stat_keys = ["Shots", "On Target", "Saves", "Tackles", "Fouls",
             "🟨 Yellow", "🟥 Red", "Corners", "Offsides", "Passes"]
col_home, col_away = st.columns(2)


def render_card(col, name, css, stats):
    rows = "".join(
        f"<div class='stat-row'><span>{k}</span>"
        f"<span class='stat-val'>{stats[k]}</span></div>"
        for k in stat_keys
    )
    rows += (
        f"<div class='stat-row'><span>Pass accuracy</span>"
        f"<span class='stat-val'>{stats['Pass %']:.0f}%</span></div>"
    )
    col.markdown(
        f"<div class='team-card {css}'>"
        f"<div class='team-name'>{name}</div>{rows}</div>",
        unsafe_allow_html=True)


render_card(col_home, "🏠 Home", "home-card", home)
render_card(col_away, "Away ✈️", "away-card", away)

st.write("")

# Live event feed (most recent first)
st.markdown("#### 📣 Live Feed")
if not events:
    st.info("No events yet. Start narrating the match into your mic!")
else:
    for e in reversed(events[-25:]):
        team = e.get("team")
        color = HOME_COLOR if team == "Home" else AWAY_COLOR if team == "Away" else "#6b7280"
        ts = e.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts).strftime("%H:%M:%S")
        except ValueError:
            pass
        parts = [p for p in [
            e.get("action"), e.get("result"),
            (f"by {e.get('player')}" if e.get("player") else None),
            (f"@ {e.get('location')}" if e.get("location") else None),
        ] if p]
        summary = " · ".join(parts) if parts else f"“{e.get('raw_text', '')}”"
        st.markdown(
            f"<div class='feed-line'>"
            f"<span class='badge' style='background:{color}'>{team or '—'}</span> "
            f"<span style='opacity:.6'>{ts}</span> &nbsp; {summary}"
            f"</div>",
            unsafe_allow_html=True)

# Raw table for debugging
with st.expander("Raw event log"):
    if events:
        st.dataframe(pd.DataFrame(events), use_container_width=True, height=300)
    else:
        st.write("Empty.")
