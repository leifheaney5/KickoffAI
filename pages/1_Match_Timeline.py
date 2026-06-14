#!/usr/bin/env python3
"""
Kickoff Pulse — Timeline page.

A visually-friendly vertical timeline of the match: a coloured icon badge for
every event (goals, cards, subs, ...), click any event to expand its full
details, filter by event type, and export the whole timeline as a PNG (the same
image is embedded into the exported PDF report).

Events logged by the audio tracker arrive with status="pending". Reviewers can
Approve, Deny, or Edit each event from the timeline. Denied events are excluded
from stats; pending events count until reviewed.
"""

import os
import sys
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brand           # noqa: E402
import control          # noqa: E402
import icons as IC      # noqa: E402
import stats as S       # noqa: E402
import timeline_image as TL  # noqa: E402

st.set_page_config(page_title=f"{brand.NAME} — Timeline",
                   page_icon=brand.LOGO_TRANSPARENT, layout="wide")
st.markdown(brand.global_css(), unsafe_allow_html=True)
st.markdown(
    "<style>div[data-testid='stHorizontalBlock']{gap:0!important}</style>",
    unsafe_allow_html=True,
)
st.markdown("""
<style>
.review-divider { border-top: 1px solid rgba(255,255,255,.12); margin: 10px 0 8px; }
</style>
""", unsafe_allow_html=True)

# Color the review action buttons by label via MutationObserver.
# Streamlit uppercases button text in CSS, so we match on uppercase.
components.html("""
<script>
const COLORS = {
  'APPROVE':      { bg: '#16a34a', border: '#15803d', text: '#fff' },
  'SAVE & APPROVE': { bg: '#16a34a', border: '#15803d', text: '#fff' },
  'DENY':         { bg: '#dc2626', border: '#b91c1c', text: '#fff' },
  'EDIT':         { bg: '#1E7BFF', border: '#1d6ee0', text: '#fff' },
  'DELETE':       { bg: '#1f2937', border: '#374151', text: '#9ca3af' },
};

function styleButtons() {
  const doc = window.parent.document;
  doc.querySelectorAll('button[data-testid="stBaseButton-secondary"]').forEach(btn => {
    const label = (btn.innerText || '').trim().toUpperCase();
    const c = COLORS[label];
    if (!c) return;
    btn.style.setProperty('background-color', c.bg,     'important');
    btn.style.setProperty('border-color',     c.border, 'important');
    btn.style.setProperty('color',            c.text,   'important');
  });
}

new MutationObserver(styleButtons)
  .observe(window.parent.document.body, { childList: true, subtree: true });
styleButtons();
</script>
""", height=0)

HOME, AWAY = IC.HOME_COLOR, IC.AWAY_COLOR

ACTIONS = sorted([
    "goal", "pass", "shot", "tackle", "save", "foul", "card",
    "corner", "offside", "dribble", "cross", "clearance",
    "interception", "substitution",
])


def event_time(e):
    return e.get("match_time") or (e.get("timestamp", "")[11:19])


def summary(e):
    parts = [p for p in [e.get("action"), e.get("result")] if p]
    return " / ".join(parts) if parts else f'"{e.get("raw_text", "")}"'


def status_tag(e) -> str:
    s = e.get("status", "")
    if s == "pending":
        return "   ·   ⏳ pending"
    if s == "denied":
        return "   ·   ✗ denied"
    return ""


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
st.markdown(
    brand.page_header("MATCH", match_name or "Timeline"),
    unsafe_allow_html=True)

pending_count = sum(1 for e in events if e.get("status") == "pending")
denied_count = sum(1 for e in events if e.get("status") == "denied")

caption_parts = [
    f"Home {score[0]} – {score[1]} Away",
    clock,
    f"{len(events)} events",
]
if pending_count:
    caption_parts.append(f"⏳ {pending_count} pending review")
st.caption("  ·  ".join(caption_parts))

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
# Controls: filter, order, denied toggle, export
# --------------------------------------------------------------------------- #
meaningful = [k for k in present if k != "other"]
default_kinds = meaningful if meaningful else present

c1, c2, c3, c4 = st.columns([3, 1.3, 1.3, 1.6])
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
    newest_first = st.toggle("Newest first", value=True)
with c3:
    show_denied = st.toggle(
        f"Show denied{f' ({denied_count})' if denied_count else ''}",
        value=False,
    )
with c4:
    if st.button("Export timeline image", type="primary", width='stretch'):
        st.session_state["tl_png"] = TL.render_to_bytes(
            events, score=score, clock=clock)

shown = [e for e in events if IC.event_kind(e) in set(kinds)]
if not show_denied:
    shown = [e for e in shown if e.get("status") != "denied"]
if newest_first:
    shown = list(reversed(shown))

if not shown:
    chatter = sum(1 for e in events if IC.event_kind(e) == "other")
    denied_hint = (
        f" {denied_count} denied event(s) are hidden — enable **Show denied** above."
        if denied_count and not show_denied else ""
    )
    st.info(
        f"No matching events for the current filter. "
        f"{chatter} background/unclassified event(s) are hidden by default — "
        f"add **Event** in the filter above to show them."
        + denied_hint
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
    ev_status = e.get("status", "")  # "" = legacy event, treated as approved
    ts = e.get("timestamp")
    uid = ts or f"idx{i}"
    edit_key = f"edit_{uid}"
    confirm_key = f"confirm_del_{uid}"

    rail_col, body_col = st.columns([0.09, 0.91])
    with rail_col:
        line = ("" if last else
                "<div style='width:2px;background:rgba(255,255,255,.18);flex:1;"
                "min-height:40px;margin-top:2px'></div>")
        st.markdown(
            f"<div style='display:flex;flex-direction:column;align-items:center;"
            f"height:100%'>{IC.badge_html(e, 34)}{line}</div>",
            unsafe_allow_html=True)
    with body_col:
        kind = IC.KIND_LABEL.get(IC.event_kind(e), "Event")
        header = f"{event_time(e)}   ·   {kind}   ·   {summary(e)}{status_tag(e)}"

        with st.expander(header):

            # ---------------------------------------------------------------- #
            # Edit form
            # ---------------------------------------------------------------- #
            if st.session_state.get(edit_key):
                st.markdown("**Edit event**")
                ef1, ef2 = st.columns(2)
                with ef1:
                    team_opts = [None, "Home", "Away"]
                    cur_team_idx = team_opts.index(e.get("team")) if e.get("team") in team_opts else 0
                    new_team = st.selectbox(
                        "Team", team_opts,
                        index=cur_team_idx,
                        key=f"f_team_{uid}",
                        format_func=lambda v: v or "—",
                    )
                    action_opts = [None] + ACTIONS
                    cur_action_idx = action_opts.index(e.get("action")) if e.get("action") in ACTIONS else 0
                    new_action = st.selectbox(
                        "Action", action_opts,
                        index=cur_action_idx,
                        key=f"f_action_{uid}",
                        format_func=lambda v: v or "—",
                    )
                    new_location = st.text_input(
                        "Location", value=e.get("location") or "",
                        key=f"f_location_{uid}",
                    )
                with ef2:
                    new_player = st.text_input(
                        "Player", value=e.get("player") or "",
                        key=f"f_player_{uid}",
                    )
                    new_result = st.text_input(
                        "Result", value=e.get("result") or "",
                        key=f"f_result_{uid}",
                        placeholder="e.g. scored, yellow, complete…",
                    )

                save_col, cancel_col = st.columns(2)
                if save_col.button("Save & approve", key=f"save_{uid}",
                                   type="primary", width='stretch'):
                    S.update_event(ts, {
                        "team": new_team or None,
                        "player": new_player.strip() or None,
                        "action": new_action or None,
                        "result": new_result.strip().lower() or None,
                        "location": new_location.strip() or None,
                        "status": "approved",
                    })
                    st.session_state.pop(edit_key, None)
                    st.session_state.pop("tl_png", None)
                    st.toast("Event updated and approved.")
                    st.rerun()
                if cancel_col.button("Cancel", key=f"cancel_{uid}", width='stretch'):
                    st.session_state.pop(edit_key, None)
                    st.rerun()

            # ---------------------------------------------------------------- #
            # Read-only field details + action buttons
            # ---------------------------------------------------------------- #
            else:
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

                st.markdown("<div class='review-divider'></div>",
                            unsafe_allow_html=True)

                # Buttons vary by current status:
                #   pending  → Approve | Deny | Edit | Delete
                #   approved → Deny | Edit | Delete
                #   denied   → Approve | Edit | Delete
                #   ""       → Deny | Edit | Delete  (legacy = treated as approved)
                if ev_status == "pending":
                    b0, b1, b2, b3 = st.columns(4)
                    if b0.button("Approve", key=f"approve_{uid}",
                                 type="primary", width='stretch'):
                        S.update_event(ts, {"status": "approved"})
                        st.session_state.pop("tl_png", None)
                        st.toast("Event approved.")
                        st.rerun()
                    if b1.button("Deny", key=f"deny_{uid}", width='stretch'):
                        S.update_event(ts, {"status": "denied"})
                        st.session_state.pop("tl_png", None)
                        st.toast("Event denied and excluded from stats.")
                        st.rerun()
                    if b2.button("Edit", key=f"edit_btn_{uid}", width='stretch'):
                        st.session_state[edit_key] = True
                        st.rerun()
                    if b3.button("Delete", key=f"del_{uid}", width='stretch'):
                        st.session_state[confirm_key] = True
                        st.rerun()

                elif ev_status == "denied":
                    b0, b1, b2 = st.columns(3)
                    if b0.button("Approve", key=f"approve_{uid}",
                                 type="primary", width='stretch'):
                        S.update_event(ts, {"status": "approved"})
                        st.session_state.pop("tl_png", None)
                        st.toast("Event approved.")
                        st.rerun()
                    if b1.button("Edit", key=f"edit_btn_{uid}", width='stretch'):
                        st.session_state[edit_key] = True
                        st.rerun()
                    if b2.button("Delete", key=f"del_{uid}", width='stretch'):
                        st.session_state[confirm_key] = True
                        st.rerun()

                else:
                    # approved or legacy (no status field)
                    b0, b1, b2 = st.columns(3)
                    if b0.button("Deny", key=f"deny_{uid}", width='stretch'):
                        S.update_event(ts, {"status": "denied"})
                        st.session_state.pop("tl_png", None)
                        st.toast("Event denied and excluded from stats.")
                        st.rerun()
                    if b1.button("Edit", key=f"edit_btn_{uid}", width='stretch'):
                        st.session_state[edit_key] = True
                        st.rerun()
                    if b2.button("Delete", key=f"del_{uid}", width='stretch'):
                        st.session_state[confirm_key] = True
                        st.rerun()

                # --- Delete two-step confirm (outside columns) -------------- #
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
                        st.session_state.pop("tl_png", None)
                        st.rerun()
                    if no.button("Cancel", key=f"no_{uid}", width='stretch'):
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
