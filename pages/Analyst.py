#!/usr/bin/env python3
"""
Kickoff Pulse — Library Analyst page.

Ask questions across the whole match library. Answers are grounded in the most
relevant matches (pgvector retrieval) and generated locally by Ollama, with the
source matches cited.
"""

import html

import streamlit as st

import analyst         # noqa: E402
import brand           # noqa: E402
import ui_helpers as UI
import embed           # noqa: E402

UI.page_setup("ANALYST", "Library Analyst")
st.caption("Ask across every match in your library. Answers are grounded in the "
           "most relevant matches and generated locally — nothing leaves this "
           "machine.")

if not embed.is_enabled():
    st.info("The library analyst needs the Postgres backend (pgvector). Start it "
            "with `docker compose up -d`, then archive a few matches.")
    st.stop()

if "analyst_chat" not in st.session_state:
    st.session_state.analyst_chat = []


def run(question: str):
    st.session_state.analyst_chat.append(("user", question, None))
    with st.spinner("Searching the library and analyzing…"):
        res = analyst.answer(question)
    if res.get("ok"):
        st.session_state.analyst_chat.append(
            ("ai", res["answer"], res.get("sources")))
    else:
        st.session_state.analyst_chat.append(
            ("ai", f"⚠ {res.get('reason', 'Unavailable.')}", None))


pending = None
cols = st.columns(len(analyst.QUICK_PROMPTS))
for (label, q), col in zip(analyst.QUICK_PROMPTS.items(), cols):
    if col.button(label, width="stretch", key=f"qa_{label}"):
        pending = q

typed = st.chat_input("Ask about your matches…")
if typed:
    pending = typed
if pending:
    run(pending)

for role, text_, sources in st.session_state.analyst_chat:
    who = "You" if role == "user" else "Library Analyst"
    st.markdown(
        f"<div class='kp-msg {role}'><div class='who'>{who}</div>"
        f"{html.escape(text_).replace(chr(10), '<br>')}</div>",
        unsafe_allow_html=True)
    if sources:
        chips = "  ·  ".join(
            f"{html.escape(s['name'])} ({s['score']*100:.0f}%)" for s in sources)
        st.caption(f"Sources: {chips}")

if st.session_state.analyst_chat:
    if st.button("Clear conversation"):
        st.session_state.analyst_chat = []
        st.rerun()
