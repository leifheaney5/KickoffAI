#!/usr/bin/env python3
"""
Kickoff Pulse — Manual Entry page.

A fillable form for logging match events without the audio tracker — useful
when the microphone isn't available, in noisy environments, or for
retrospective corrections.

Quick Actions at the top let you log the most common events in two taps (pick
team, pick action). The Full Form below handles everything else with all fields
exposed.

Manual entries are marked status="approved" immediately — no review step needed
since the user is entering them directly.
"""

import os
import sys
from datetime import datetime, timezone

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brand           # noqa: E402
import control         # noqa: E402
import icons as IC     # noqa: E402
import stats as S      # noqa: E402

st.set_page_config(page_title=f"{brand.NAME} — Manual Entry",
                   page_icon=brand.LOGO_TRANSPARENT, layout="wide")
st.markdown(brand.global_css(), unsafe_allow_html=True)
st.markdown(
    "<style>div[data-testid='stHorizontalBlock']{gap:4px!important}</style>",
    unsafe_allow_html=True,
)

# Color quick-action buttons and the Log Event submit button by text label.
components.html("""
<script>
const COLORS = {
  'GOAL':     { bg: '#16a34a', border: '#15803d' },
  'SHOT':     { bg: '#6366f1', border: '#4f46e5' },
  'SAVE':     { bg: '#0891b2', border: '#0e7490' },
  'FOUL':     { bg: '#f97316', border: '#ea580c' },
  'TACKLE':   { bg: '#7c3aed', border: '#6d28d9' },
  'YELLOW':   { bg: '#ca8a04', border: '#a16207' },
  'RED':      { bg: '#dc2626', border: '#b91c1c' },
  'CORNER':   { bg: '#475569', border: '#334155' },
  'OFFSIDE':  { bg: '#475569', border: '#334155' },
  'SUB':      { bg: '#4DA3FF', border: '#1E7BFF' },
  'LOG EVENT':{ bg: '#16a34a', border: '#15803d' },
};
function styleButtons() {
  window.parent.document
    .querySelectorAll('button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-primary"]')
    .forEach(btn => {
      const label = (btn.innerText || '').trim().toUpperCase();
      const c = COLORS[label];
      if (!c) return;
      btn.style.setProperty('background-color', c.bg,     'important');
      btn.style.setProperty('border-color',     c.border, 'important');
      btn.style.setProperty('color',            '#fff',   'important');
    });
}
new MutationObserver(styleButtons)
  .observe(window.parent.document.body, { childList: true, subtree: true });
styleButtons();
</script>
""", height=0)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
ACTIONS = [
    "goal", "shot", "save", "pass", "tackle", "foul", "card",
    "corner", "offside", "dribble", "cross", "clearance",
    "interception", "substitution",
]

# Each quick action: (display label, action value, default result)
QUICK = [
    ("Goal",    "goal",         "scored"),
    ("Shot",    "shot",         "on target"),
    ("Save",    "save",         "saved"),
    ("Foul",    "foul",         None),
    ("Tackle",  "tackle",       None),
    ("Yellow",  "card",         "yellow"),
    ("Red",     "card",         "red"),
    ("Corner",  "corner",       None),
    ("Offside", "offside",      None),
    ("Sub",     "substitution", None),
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def current_match_time() -> str:
    state = control.load_control()
    main_clk, added, _half = control.clock_label(state["timer"])
    return f"{main_clk}{(' ' + added) if added else ''}"


def log_event(team, player, action, result, location, match_time=None) -> dict:
    record = {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "match_time": match_time or current_match_time(),
        "raw_text":   None,
        "status":     "approved",
        "team":       team or None,
        "player":     player.strip() if player else None,
        "action":     action or None,
        "result":     result.strip().lower() if result else None,
        "location":   location.strip() if location else None,
    }
    all_events = S.load_events()
    all_events.append(record)
    S.save_events(all_events)
    return record


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
state  = control.load_control()
events = S.load_events()
home   = S.team_stats(events, "Home")
away   = S.team_stats(events, "Away")
main_clk, added, half = control.clock_label(state["timer"])
clock  = f"{main_clk}{(' ' + added) if added else ''} ({half})"

match_name = (state.get("match_name") or "").strip()
st.markdown(brand.page_header("MANUAL", match_name or "Entry"),
            unsafe_allow_html=True)
st.caption(
    f"Home {home['Goals']} – {away['Goals']} Away  ·  {clock}  ·  {len(events)} events"
)

st.divider()

# --------------------------------------------------------------------------- #
# Quick Actions
# --------------------------------------------------------------------------- #
st.markdown("#### Quick Actions")
st.caption("Type an optional player, then tap an action button for Home or Away.")

qa_player = st.text_input(
    "Player (optional)",
    placeholder="#7 or player name",
    key="qa_player",
)

home_col, away_col = st.columns(2)

for team_label, team_val, col, key_prefix in [
    ("HOME", "Home", home_col, "h"),
    ("AWAY", "Away", away_col, "a"),
]:
    color = IC.HOME_COLOR if team_val == "Home" else IC.AWAY_COLOR
    col.markdown(
        f"<div style='font-weight:700;color:{color};font-size:13px;"
        f"letter-spacing:.07em;margin-bottom:4px'>{team_label}</div>",
        unsafe_allow_html=True,
    )
    # 5 columns per row, 2 rows of 5 = 10 actions
    btn_cols = col.columns(5)
    for idx, (label, action, result) in enumerate(QUICK):
        if btn_cols[idx % 5].button(
                label,
                key=f"qa_{key_prefix}_{action}_{result}",
                width="stretch"):
            r = log_event(team_val, qa_player, action, result, None)
            st.toast(f"{team_label} — {label} logged at {r['match_time']}.")
            st.rerun()

st.divider()

# --------------------------------------------------------------------------- #
# Full Form
# --------------------------------------------------------------------------- #
st.markdown("#### Full Event Form")
st.caption("All fields — use when you need to specify location, custom result, or match time.")

with st.form("manual_entry", clear_on_submit=True):
    row1 = st.columns([1, 1, 1])
    with row1[0]:
        team = st.selectbox(
            "Team *", [None, "Home", "Away"],
            format_func=lambda v: v or "—",
        )
    with row1[1]:
        action = st.selectbox(
            "Action *", [None] + ACTIONS,
            format_func=lambda v: v or "—",
        )
    with row1[2]:
        result = st.text_input("Result",
                               placeholder="scored, yellow, complete, on target…")

    row2 = st.columns([1, 1, 1])
    with row2[0]:
        player = st.text_input("Player", placeholder="#7 or name")
    with row2[1]:
        location = st.text_input("Location", placeholder="box, left wing, midfield…")
    with row2[2]:
        match_time_input = st.text_input(
            "Match time", value=current_match_time(),
            placeholder="00:00",
        )

    submitted = st.form_submit_button(
        "Log Event", type="primary", use_container_width=True)

    if submitted:
        if not team or not action:
            st.error("Team and Action are required.")
        else:
            r = log_event(team, player, action, result, location, match_time_input)
            suffix = f" / {r['result']}" if r["result"] else ""
            st.success(
                f"Logged: **{team} {action}**{suffix} at {r['match_time']}"
            )

st.divider()

# --------------------------------------------------------------------------- #
# Recent manual entries
# --------------------------------------------------------------------------- #
manual = [
    e for e in reversed(S.load_events())
    if e.get("raw_text") is None and e.get("status") == "approved"
][:10]

st.markdown("#### Recent manual entries")
if not manual:
    st.caption("Nothing logged manually yet.")
else:
    for e in manual:
        kind    = IC.KIND_LABEL.get(IC.event_kind(e), "Event")
        parts   = [p for p in [e.get("action"), e.get("result")] if p]
        summary = " / ".join(parts) or "—"
        team_tag   = f"**{e.get('team')}** · " if e.get("team")   else ""
        player_tag = f"{e.get('player')} · "   if e.get("player") else ""
        st.markdown(
            f"`{e.get('match_time', '—')}` &nbsp;"
            f"{IC.badge_html(e, 20)} "
            f"{team_tag}{player_tag}{summary}",
            unsafe_allow_html=True,
        )
