#!/usr/bin/env python3
"""
Kickoff Pulse — Season page.

Cross-match analytics over the whole library: a league table, top scorers, and
goals-over-time, computed from the matches + mirrored events in the database.
"""

import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brand           # noqa: E402
import db              # noqa: E402
import season          # noqa: E402

st.set_page_config(page_title=f"{brand.NAME} — Season",
                   page_icon=brand.LOGO_TRANSPARENT, layout="wide")
st.markdown(brand.global_css(), unsafe_allow_html=True)

st.markdown(brand.page_header("SEASON", "Season Analytics"),
            unsafe_allow_html=True)


@st.cache_data(ttl=10)
def load_season():
    """Pull matches + goal events (with real team names) from the DB."""
    db.init_db()
    matches, goals, timeline = [], [], []
    with db.session() as s:
        for m in s.query(db.Match).order_by(db.Match.played_on).all():
            matches.append({
                "name": m.name, "competition": m.competition or "",
                "played_on": m.played_on, "home_team": m.home_team,
                "away_team": m.away_team, "home_score": m.home_score,
                "away_score": m.away_score,
            })
            timeline.append({
                "match": m.name,
                "date": m.played_on.isoformat() if m.played_on else "",
                "goals": (m.home_score or 0) + (m.away_score or 0),
            })
            role_name = {"Home": m.home_team, "Away": m.away_team}
            for e in m.events:
                if e.action == "goal" or e.result == "scored":
                    goals.append({"player": e.player,
                                  "team": role_name.get(e.team) or e.team or ""})
    return matches, goals, timeline


matches, goals, timeline = load_season()

if not matches:
    st.info("No matches in the library yet. Archive matches from the dashboard "
            "(or import past reports on the Match Library page) to see season "
            "analytics here.")
    st.stop()

# ---- Overview ------------------------------------------------------------- #
total_goals = sum(t["goals"] for t in timeline)
n = len(matches)
o1, o2, o3 = st.columns(3)
o1.metric("Matches", n)
o2.metric("Goals", total_goals)
o3.metric("Goals / match", f"{total_goals / n:.1f}" if n else "0")

st.write("")

# ---- League table --------------------------------------------------------- #
st.markdown(brand.section("League table"), unsafe_allow_html=True)
standings = season.team_standings(matches)
if standings:
    df = pd.DataFrame(standings)[
        ["team", "P", "W", "D", "L", "GF", "GA", "GD", "Pts"]]
    df.columns = ["Team", "P", "W", "D", "L", "GF", "GA", "GD", "Pts"]
    st.dataframe(df, width="stretch", hide_index=True)
else:
    st.caption("Add team names in Match setup so results can be tabulated.")

st.write("")

# ---- Top scorers ---------------------------------------------------------- #
st.markdown(brand.section("Top scorers"), unsafe_allow_html=True)
scorers = season.top_scorers(goals)
if scorers:
    df = pd.DataFrame(scorers)
    df.columns = ["Player", "Team", "Goals"]
    st.dataframe(df, width="stretch", hide_index=True)
else:
    st.caption("No goals recorded yet.")

st.write("")

# ---- Goals over time ------------------------------------------------------ #
st.markdown(brand.section("Goals per match"), unsafe_allow_html=True)
tdf = pd.DataFrame(timeline)
if not tdf.empty and tdf["goals"].sum() > 0:
    st.bar_chart(tdf.set_index("match")["goals"], height=260)
else:
    st.caption("Not enough data to chart yet.")
