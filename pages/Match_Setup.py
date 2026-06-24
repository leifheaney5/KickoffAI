#!/usr/bin/env python3
"""
Match Setup — everything you fill in before kickoff.

Match identity (date, competition, name), both teams' names and lineups, and the
formation + numbered roster the tracker uses to name players and pick a side.
This all used to crowd the sidebar and the bottom of the home page.
"""

from datetime import date as _date

import streamlit as st

import brand
import control
import ui_helpers as UI

st.markdown(brand.app_css(), unsafe_allow_html=True)
st.markdown(brand.page_header("SET UP", "Match Setup"), unsafe_allow_html=True)

state = control.load_control()

# ---- Match identity ------------------------------------------------------- #
st.markdown(brand.section("Match details"), unsafe_allow_html=True)
mc1, mc2 = st.columns(2)
_md = (state.get("match_date") or "").strip()
try:
    _md_val = _date.fromisoformat(_md) if _md else _date.today()
except ValueError:
    _md_val = _date.today()
_match_date = mc1.date_input("Match date", value=_md_val, key="setup_date")
_competition = mc2.text_input(
    "Competition", value=state.get("competition", ""),
    placeholder="e.g. Spring League — Round 12", key="setup_competition")
_match_name = st.text_input(
    "Match name", value=state.get("match_name", ""),
    placeholder="e.g. Eagles vs Hawks — Jun 7", key="setup_match_name")
if st.button("Save match details", type="primary", use_container_width=True,
             key="save_match_setup"):
    state["match_date"] = _match_date.isoformat() if _match_date else ""
    state["competition"] = _competition.strip()
    state["match_name"] = _match_name.strip()
    control.save_control(state)
    st.success("Saved.")

st.write("")

# ---- Team names + lineups (free text) ------------------------------------- #
st.markdown(brand.section("Teams"), unsafe_allow_html=True)
_teams = state.get("teams", {"home": {"name": "", "lineup": ""},
                             "away": {"name": "", "lineup": ""}})
tc1, tc2 = st.columns(2)
with tc1:
    st.caption("HOME")
    _home_name = st.text_input(
        "Team name", value=_teams.get("home", {}).get("name", ""),
        placeholder="e.g. Eagles", key="setup_home_name")
    _home_lineup = st.text_area(
        "Lineup", value=_teams.get("home", {}).get("lineup", ""),
        placeholder="#1 Goalkeeper\n#5 Defender\n#10 Captain\n...",
        height=180, key="setup_home_lineup")
with tc2:
    st.caption("AWAY")
    _away_name = st.text_input(
        "Team name", value=_teams.get("away", {}).get("name", ""),
        placeholder="e.g. Hawks", key="setup_away_name")
    _away_lineup = st.text_area(
        "Lineup", value=_teams.get("away", {}).get("lineup", ""),
        placeholder="#1 Goalkeeper\n#5 Defender\n#10 Captain\n...",
        height=180, key="setup_away_lineup")

if st.button("Save teams", type="primary", use_container_width=True,
             key="save_team_info"):
    state["teams"] = {
        "home": {"name": _home_name.strip(), "lineup": _home_lineup.strip()},
        "away": {"name": _away_name.strip(), "lineup": _away_lineup.strip()},
    }
    control.save_control(state)
    st.success("Saved.")

st.write("")

# ---- Numbered roster + formation (used by the tracker + report) ----------- #
st.markdown(brand.section("Lineups & formation"), unsafe_allow_html=True)
st.caption("Enter each side's formation and roster (shirt number + name). "
           "The brain maps a spoken “number 6” to that player's name and team; "
           "the report lists both lineups.")
lineups = state.get("lineups") or {}
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
    UI.roster_df(lineups, "Home"), num_rows="dynamic", width="stretch",
    hide_index=True, column_config=colcfg, key="home_roster")
away_roster = ec2.data_editor(
    UI.roster_df(lineups, "Away"), num_rows="dynamic", width="stretch",
    hide_index=True, column_config=colcfg, key="away_roster")
if st.button("Save lineups", type="primary", width="stretch"):
    state["lineups"] = {
        "Home": {"formation": home_formation.strip(),
                 "players": UI.df_to_players(home_roster)},
        "Away": {"formation": away_formation.strip(),
                 "players": UI.df_to_players(away_roster)},
    }
    control.save_control(state)
    st.success("Lineups saved — the tracker now uses them for new events.")
