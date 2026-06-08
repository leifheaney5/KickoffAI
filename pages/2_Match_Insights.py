#!/usr/bin/env python3
"""
Kickoff Pulse — Insights page.

Turns the live event log into analysis: a decaying **momentum** graph showing
when the game swings, headline efficiency numbers, and an **AI analyst** you can
ask anything about the match (answered locally by the Ollama model — no cloud).
"""

import html
import os
import sys

import altair as alt
import pandas as pd
import requests
import streamlit as st

# Make the project root importable when run as a Streamlit page.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brand            # noqa: E402
import control          # noqa: E402
import insights as IN   # noqa: E402
import stats as S       # noqa: E402

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

st.set_page_config(page_title=f"{brand.NAME} — Insights",
                   page_icon=brand.LOGO_TRANSPARENT, layout="wide")
st.markdown(brand.app_css(), unsafe_allow_html=True)
st.markdown(
    """
    <style>
      .kp-ana { display:flex; flex-direction:column; }
      .kp-msg { border-radius:14px; padding:11px 16px; margin:6px 0; max-width:86%;
                line-height:1.5; animation:kpFade .3s ease both; }
      .kp-msg.user { align-self:flex-end; color:#fff;
            background:linear-gradient(135deg, rgba(30,123,255,.32), rgba(43,231,255,.18));
            border:1px solid rgba(43,231,255,.36); }
      .kp-msg.ai { align-self:flex-start; color:var(--txt);
            background:var(--glass); border:1px solid var(--glass-bd); }
      .kp-msg .who { font-family:var(--fd); font-size:.64rem; letter-spacing:.14em;
            text-transform:uppercase; color:var(--muted); margin-bottom:4px; }
    </style>
    """,
    unsafe_allow_html=True,
)

HOME, AWAY = brand.HOME, brand.AWAY

# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
events = S.load_events()
state = control.load_control()
home = S.team_stats(events, "Home")
away = S.team_stats(events, "Away")
poss = S.possession(home, away)
main_clk, added, half = control.clock_label(state["timer"])
clock = f"{main_clk}{(' ' + added) if added else ''} ({half})"
match_name = (state.get("match_name") or "").strip()

st.markdown(brand.header_html(), unsafe_allow_html=True)
st.markdown(f"# {match_name or 'Match Insights'}")
st.caption(f"AI analysis · Home {home['Goals']}–{away['Goals']} Away · {clock} · "
           f"{len(events)} events")

if not events:
    st.info("No events yet. Narrate the match on the dashboard, then come back "
            "for momentum and AI analysis.")
    st.stop()

# --------------------------------------------------------------------------- #
# Headline numbers
# --------------------------------------------------------------------------- #
m = IN.headline_metrics(events, home, away)
lead = m["momentum_leader"] or "Even"
lead_color = HOME if lead == "Home" else AWAY if lead == "Away" else "#9fb6dd"


def chip(label, value, color="#fff"):
    return (f"<div class='kp-chip'><span class='l'>{label}</span>"
            f"<span class='v' style='color:{color}'>{value}</span></div>")


st.markdown(
    "<div class='kp-status'>"
    + chip("Momentum", lead, lead_color)
    + chip("Shots", f"{m['shots'][0]}–{m['shots'][1]}")
    + chip("On target", f"{m['on_target'][0]}–{m['on_target'][1]}")
    + chip("Conversion", f"{m['conversion'][0]}%–{m['conversion'][1]}%")
    + chip("Events", m["events"])
    + "</div>",
    unsafe_allow_html=True)

st.write("")

# --------------------------------------------------------------------------- #
# Momentum graph
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Momentum — the swing of the match"),
            unsafe_allow_html=True)
rows = IN.momentum_series(events)
if any(r["momentum"] for r in rows):
    df = pd.DataFrame(rows)
    base = alt.Chart(df).encode(
        x=alt.X("minute:Q", title="Match minute",
                axis=alt.Axis(format="d")))
    area_a = base.mark_area(interpolate="monotone", opacity=0.85,
                            color=AWAY).encode(y=alt.Y("away:Q", title="Momentum"))
    area_h = base.mark_area(interpolate="monotone", opacity=0.85,
                            color=HOME).encode(y="home:Q")
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
        color="rgba(255,255,255,.35)", strokeDash=[4, 4]).encode(y="y:Q")
    chart = (area_a + area_h + zero).properties(height=250).configure(
        background="transparent").configure_view(strokeWidth=0).configure_axis(
        grid=False, labelColor="#9fb6dd", titleColor="#cfe0ff",
        domainColor="#33415c", tickColor="#33415c",
        labelFont="Spline Sans Mono", titleFont="Chakra Petch")
    st.altair_chart(chart, use_container_width=True)
    st.caption("Above the line = **Home** pressure · below = **Away**. Recent "
               "events weigh most, so the curve reads like live momentum.")
else:
    st.caption("Not enough team-attributed events to chart momentum yet.")

st.write("")

# --------------------------------------------------------------------------- #
# AI analyst
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Ask the analyst"), unsafe_allow_html=True)
st.caption("Powered locally by the Ollama model — your match data never leaves "
           "this machine.")

if "kp_chat" not in st.session_state:
    st.session_state.kp_chat = []


def ask_analyst(question: str, context: str) -> str:
    payload = {
        "model": OLLAMA_MODEL, "stream": False, "options": {"temperature": 0.3},
        "messages": [
            {"role": "system", "content": IN.SYSTEM_PROMPT},
            {"role": "user",
             "content": f"MATCH DATA:\n{context}\n\nQUESTION: {question}"},
        ],
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def run_query(q: str):
    ctx = IN.build_context(events, home, away, poss, clock)
    st.session_state.kp_chat.append(("user", q))
    try:
        with st.spinner("Analyzing the match…"):
            ans = ask_analyst(q, ctx)
    except Exception as exc:
        ans = (f"⚠ Couldn't reach the local model ({exc}). "
               f"Make sure Ollama is running (`ollama serve`).")
    st.session_state.kp_chat.append(("ai", ans))


# Quick one-tap prompts + free-text input both funnel into `pending`.
pending = None
qcols = st.columns(len(IN.QUICK_PROMPTS))
for (label, q), col in zip(IN.QUICK_PROMPTS.items(), qcols):
    if col.button(label, width="stretch", key=f"quick_{label}"):
        pending = q

prompt = st.chat_input("Ask anything about the match…")
if prompt:
    pending = prompt

if pending:
    run_query(pending)

# Render conversation (newest exchange last).
if st.session_state.kp_chat:
    bubbles = "".join(
        f"<div class='kp-msg {role}'>"
        f"<div class='who'>{'You' if role == 'user' else 'Kickoff Pulse AI'}</div>"
        f"{html.escape(text).replace(chr(10), '<br>')}</div>"
        for role, text in st.session_state.kp_chat
    )
    st.markdown(f"<div class='kp-ana'>{bubbles}</div>", unsafe_allow_html=True)
    if st.button("Clear conversation"):
        st.session_state.kp_chat = []
        st.rerun()
else:
    st.caption("Tap a prompt above or type a question to get a live read on the "
               "match.")
