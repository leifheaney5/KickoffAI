#!/usr/bin/env python3
"""
KickoffAI — Timeline page.

A visually-friendly vertical timeline of the match: a coloured icon badge for
every event (goals, cards, subs, ...), click any event to expand its full
details, filter by event type, and export the whole timeline as a PNG (the same
image is embedded into the exported PDF report).
"""

import os
import sys
from datetime import datetime

import streamlit as st

# Make the project root importable when run as a Streamlit page.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import control          # noqa: E402
import icons as IC      # noqa: E402
import stats as S       # noqa: E402
import timeline_image as TL  # noqa: E402

st.set_page_config(page_title="KickoffAI — Timeline", layout="wide")

HOME, AWAY = IC.HOME_COLOR, IC.AWAY_COLOR

st.markdown(
    """
    <style>
      .block-container { max-width: 1100px; }
      /* tighten the gap between timeline rows so the rail looks continuous */
      div[data-testid="stHorizontalBlock"] { gap: 0 !important; }
      .stExpander { border: 1px solid #eceef1 !important; border-radius: 10px !important; }
      .det { display:flex; justify-content:space-between; padding:4px 0;
             border-bottom:1px solid #f1f3f5; font-size:.95rem; }
      .det:last-child { border-bottom:none; }
      .det .k { color:#6b7280; }
      .legend { display:flex; flex-wrap:wrap; gap:14px; margin:4px 0 2px; }
      .legend .item { display:flex; align-items:center; gap:6px; font-size:.85rem;
                      color:#4b5563; }
    </style>
    """,
    unsafe_allow_html=True,
)


def event_time(e):
    return e.get("match_time") or (e.get("timestamp", "")[11:19])


def summary(e):
    parts = [p for p in [e.get("action"), e.get("result")] if p]
    return " / ".join(parts) if parts else f'"{e.get("raw_text", "")}"'


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
events = S.load_events()
state = control.load_control()
home = S.team_stats(events, "Home")
away = S.team_stats(events, "Away")
main_clk, added, half = control.clock_label(state["timer"])
clock = f"{main_clk}{(' ' + added) if added else ''} ({half})"
score = (home["Goals"], away["Goals"])

match_name = (state.get("match_name") or "").strip()
st.markdown(f"# {match_name}" if match_name else "# Match Timeline")
st.caption(f"{'Match Timeline · ' if match_name else ''}"
           f"Home {score[0]} - {score[1]} Away   ·   {clock}   ·   "
           f"{len(events)} events")

if not events:
    st.info("No events yet. Narrate the match on the dashboard, then come back "
            "to see the timeline build itself.")
    st.stop()

# Legend
_SAMPLE = {
    "goal": {"action": "goal"},
    "yellow": {"action": "card", "result": "yellow"},
    "red": {"action": "card", "result": "red"},
    "sub": {"action": "substitution"},
}
present = []
for e in events:
    k = IC.event_kind(e)
    if k not in present:
        present.append(k)
legend = "".join(
    f"<span class='item'>{IC.badge_html(_SAMPLE.get(k, {'action': k}), 20)}"
    f"{IC.KIND_LABEL.get(k, k)}</span>" for k in present
)
st.markdown(f"<div class='legend'>{legend}</div>", unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Controls: filter, order, export
# --------------------------------------------------------------------------- #
# Default to meaningful events; background chatter ("other", null actions) is
# hidden unless the user opts in via the filter.
meaningful = [k for k in present if k != "other"]
default_kinds = meaningful if meaningful else present

c1, c2, c3 = st.columns([3, 1.3, 1.6])
with c1:
    kinds = st.multiselect(
        "Show event types",
        options=present,
        default=default_kinds,
        format_func=lambda k: IC.KIND_LABEL.get(k, k),
        label_visibility="collapsed",
        placeholder="Filter event types…",
    )
with c2:
    newest_first = st.toggle("Newest first", value=False)
with c3:
    if st.button("Export timeline image", type="primary",
                 width='stretch'):
        st.session_state["tl_png"] = TL.render_to_bytes(
            events, score=score, clock=clock)

shown = [e for e in events if IC.event_kind(e) in set(kinds)]
if newest_first:
    shown = list(reversed(shown))

if not shown:
    chatter = sum(1 for e in events if IC.event_kind(e) == "other")
    st.info(
        f"No matching events for the current filter. "
        f"{chatter} background/unclassified event(s) are hidden by default — "
        f"add **Event** in the filter above to show them."
    )

# Exported image preview + download
png = st.session_state.get("tl_png")
if png:
    with st.expander("Timeline image (PNG)", expanded=True):
        st.image(png, width='stretch')
        st.download_button(
            "Download timeline.png", png,
            file_name=f"match_timeline_{datetime.now():%Y%m%d_%H%M%S}.png",
            mime="image/png")
        st.caption("This image is also embedded into the exported PDF report.")

st.divider()

# --------------------------------------------------------------------------- #
# Interactive vertical timeline
# --------------------------------------------------------------------------- #
for i, e in enumerate(shown):
    last = i == len(shown) - 1
    rail_col, body_col = st.columns([0.09, 0.91])
    with rail_col:
        line = ("" if last else
                "<div style='width:2px;background:#e5e7eb;flex:1;"
                "min-height:40px;margin-top:2px'></div>")
        st.markdown(
            f"<div style='display:flex;flex-direction:column;align-items:center;"
            f"height:100%'>{IC.badge_html(e, 34)}{line}</div>",
            unsafe_allow_html=True)
    with body_col:
        kind = IC.KIND_LABEL.get(IC.event_kind(e), "Event")
        header = f"{event_time(e)}   ·   {kind}   ·   {summary(e)}"
        with st.expander(header):
            fields = [
                ("Team", e.get("team")),
                ("Player", e.get("player")),
                ("Action", e.get("action")),
                ("Result", e.get("result")),
                ("Location", e.get("location")),
                ("Match time", e.get("match_time")),
                ("Logged (UTC)", e.get("timestamp")),
            ]
            rows = "".join(
                f"<div class='det'><span class='k'>{k}</span>"
                f"<span>{v if v not in (None, '') else '—'}</span></div>"
                for k, v in fields
            )
            st.markdown(rows, unsafe_allow_html=True)
            if e.get("raw_text"):
                st.caption(f'Heard: "{e["raw_text"]}"')

            # --- Delete (two-step confirm) --------------------------------- #
            ts = e.get("timestamp")
            uid = ts or f"idx{i}"
            confirm_key = f"confirm_del_{uid}"
            if st.session_state.get(confirm_key):
                st.warning("Delete this event? This can't be undone.")
                yes, no, _ = st.columns([1, 1, 3])
                if yes.button("Confirm delete", key=f"yes_{uid}",
                              type="primary", width='stretch'):
                    if S.delete_event(ts):
                        st.toast("Event deleted.")
                    else:
                        st.toast("Couldn't find that event — it may already "
                                 "be gone.")
                    st.session_state.pop(confirm_key, None)
                    st.session_state.pop("tl_png", None)  # stale image
                    st.rerun()
                if no.button("Cancel", key=f"no_{uid}", width='stretch'):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
            elif st.button("🗑 Delete event", key=f"del_{uid}"):
                st.session_state[confirm_key] = True
                st.rerun()
