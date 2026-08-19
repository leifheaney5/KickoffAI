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
import auth            # noqa: E402
import db              # noqa: E402
import season          # noqa: E402

st.set_page_config(page_title=f"{brand.NAME} — Season",
                   page_icon=brand.LOGO_TRANSPARENT, layout="wide")
st.markdown(brand.global_css(), unsafe_allow_html=True)

st.markdown(brand.page_header("SEASON", "Season Analytics"),
            unsafe_allow_html=True)


@st.cache_data(ttl=10)
def load_season(_viewer_id=None):
    """Pull matches + goal events (with real team names) from the DB.

    Scoped to what the signed-in user may see. `_viewer_id` is part of the cache
    key (the leading underscore keeps Streamlit from hashing it as data) so two
    users on one machine never see each other's cached library.
    """
    db.init_db()
    matches, goals, timeline = [], [], []
    viewer = auth.current_user()
    with db.session() as s:
        for m in s.query(db.Match).order_by(db.Match.played_on).all():
            if not auth.can_view_match(viewer, m):
                continue
            matches.append({
                "name": m.name, "competition": m.competition or "",
                "played_on": m.played_on, "home_team": m.home_team,
                "away_team": m.away_team, "home_score": m.home_score,
                "away_score": m.away_score,
                "vision_verdict": m.vision_verdict or "",
                "vision_ball_rate": m.vision_ball_rate or 0.0,
                "vision_home_possession": m.vision_home_possession or 0.0,
                "vision_away_possession": m.vision_away_possession or 0.0,
                "vision_passes": m.vision_passes or 0,
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


me = auth.current_user()
matches, goals, timeline = load_season(me["id"] if me else None)

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

st.write("")

# --------------------------------------------------------------------------- #
# Camera coverage + possession trend
#
# Only *measured* runs are trended. An indicative run is worth showing on its own
# match report, but averaging it into a season line silently corrupts the line —
# a run that rarely saw the ball misattributes possession rather than just adding
# noise. Coverage is stated first so the trend always has an honest denominator.
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Camera coverage"), unsafe_allow_html=True)
cov = season.vision_coverage(matches)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Matches with camera", f"{cov['measured'] + cov['indicative']}/{cov['matches']}")
c2.metric("Measured", cov["measured"])
c3.metric("Indicative", cov["indicative"])
c4.metric("Mean ball rate", f"{cov['mean_ball_rate'] * 100:.0f}%"
          if cov["measured"] else "—")

if not cov["measured"]:
    st.caption("No match yet has a camera run good enough to trend. Runs graded "
               "*indicative* still appear on their own match report — they are "
               "held out of season trends so a low-confidence run cannot skew "
               "them.")
else:
    trend = season.possession_trend(matches)
    if trend:
        tf = pd.DataFrame(trend)
        tf["match"] = tf["home_team"] + " v " + tf["away_team"]
        st.markdown(brand.section("Possession trend (measured runs only)"),
                    unsafe_allow_html=True)
        st.line_chart(tf.set_index("match")[["home_possession",
                                             "away_possession"]], height=260)
        st.caption(f"{len(trend)} of {cov['matches']} matches have a measured "
                   "camera run.")
