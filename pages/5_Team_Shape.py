#!/usr/bin/env python3
"""
Kickoff Pulse — Team Shape & Heatmaps page (Phase 1 spatial analytics).

Post-match spatial analysis from the vision pipeline's match_stats.json: team
and per-player heatmaps, a formation (average-position) diagram, team-shape
metrics (compactness, width, depth) and territory share. Player-only — no ball
required — so it works today. Coordinates are image-space until pitch
calibration lands, then become true tactical coordinates automatically.
"""

import os
import sys

import requests
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brand           # noqa: E402
import control         # noqa: E402
import icons as IC     # noqa: E402

st.set_page_config(page_title=f"{brand.NAME} — Team Shape",
                   page_icon=brand.LOGO_TRANSPARENT, layout="wide")
st.markdown(brand.global_css(), unsafe_allow_html=True)

try:
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from vision import analytics
    DEPS_OK, DEPS_ERR = True, ""
except Exception as exc:  # pragma: no cover - import guard
    DEPS_OK, DEPS_ERR = False, str(exc)

state = control.load_control()
match_name = (state.get("match_name") or "").strip()
st.markdown(brand.page_header("SHAPE", match_name or "Team Shape & Heatmaps"),
            unsafe_allow_html=True)

if not DEPS_OK:
    st.error("Analytics dependencies are not installed.")
    st.code("pip install -r vision/requirements.txt", language="bash")
    st.caption(f"Import error: {DEPS_ERR}")
    st.stop()


# --------------------------------------------------------------------------- #
# Pitch drawing
# --------------------------------------------------------------------------- #
def draw_pitch(ax):
    ax.set_facecolor("#2f7d34")
    ax.set_xlim(-2, 102)
    ax.set_ylim(-2, 102)
    line = dict(color="white", lw=1.2)
    ax.plot([0, 100, 100, 0, 0], [0, 0, 100, 100, 0], **line)
    ax.plot([50, 50], [0, 100], **line)
    ax.add_patch(plt.Circle((50, 50), 9, fill=False, edgecolor="white", lw=1.2))
    # Penalty boxes (approx, normalised).
    ax.plot([0, 16, 16, 0], [21, 21, 79, 79], **line)
    ax.plot([100, 84, 84, 100], [21, 21, 79, 79], **line)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def heatmap_fig(points, title, bins):
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    H, _xe, _ye = analytics.heatmap(points, bins=(bins, max(4, bins * 2 // 3)))
    ax.imshow(H.T, origin="lower", extent=[0, 100, 0, 100],
              cmap="inferno", alpha=0.72, aspect="auto", interpolation="bilinear")
    draw_pitch(ax)
    ax.set_title(title, color="#e5e7eb", fontsize=11)
    fig.patch.set_alpha(0)
    return fig


def formation_fig(positions, title):
    fig, ax = plt.subplots(figsize=(7.0, 4.4))
    draw_pitch(ax)
    for p in positions:
        col = (IC.HOME_COLOR if p["team"] == "Home"
               else IC.AWAY_COLOR if p["team"] == "Away" else "#9ca3af")
        ax.scatter(p["x"], p["y"], s=240, color=col, edgecolors="white",
                   linewidths=1.2, zorder=3)
        label = p["id"].split("_")[-1].replace("No", "").replace("trk", "t")
        ax.text(p["x"], p["y"], label, color="white", fontsize=7,
                ha="center", va="center", zorder=4, fontweight="bold")
    ax.set_title(title, color="#e5e7eb", fontsize=11)
    fig.patch.set_alpha(0)
    return fig


# --------------------------------------------------------------------------- #
# Data source
# --------------------------------------------------------------------------- #
candidates = ["match_stats.json", "match_stats.soccer_rf.json",
              "match_stats.soccer.json", "match_stats.demo.json"]
default_stats = next((c for c in candidates if os.path.exists(c)), "match_stats.json")

c1, c2 = st.columns([3, 1])
stats_path = c1.text_input("match_stats.json path", value=default_stats)
home_lr = c2.toggle("Home attacks L→R", value=True,
                    help="Orientation for territory / thirds.")

if not os.path.exists(stats_path):
    st.info("No stats file yet. Run the **Video Analysis** page first to "
            "produce a match_stats.json.")
    st.stop()

try:
    stats = analytics.load_stats(stats_path)
except Exception as exc:
    st.error(f"Could not read {stats_path}: {exc}")
    st.stop()

n_frames = len(analytics.frames(stats))
teams = analytics.teams_present(stats)
n_players = len(analytics.collect_player_points(stats))
st.caption(f"{n_frames} frames · {n_players} tracked players · "
           f"teams: {', '.join(teams) if teams else 'unlabelled'}")
if n_frames == 0:
    st.warning("This file has no tracking frames to analyse.")
    st.stop()

coord_space = stats.get("tracking_data", {}).get("coordinate_space", "image")
if coord_space != "pitch":
    st.warning(
        "**Uncalibrated — image space.** Positions are raw camera pixels, so "
        "perspective squashes the pitch's depth (players collapse toward one "
        "band) and the team / horizontal split is meaningful while vertical "
        "spread is not. Add a fixed-camera 4-point calibration (Phase 2) for "
        "true pitch geometry.")
if n_players > 30:
    st.info(
        f"{n_players} track ids for ~22 players — IDs fragment under camera "
        "panning/occlusion. Team heatmaps are unaffected (they pool all "
        "detections); the per-player formation is filtered below, and "
        "jersey-number OCR (Phase 4) fixes identity for good.")

bins = st.slider("Heatmap resolution", 12, 40, 22)
st.divider()

# --------------------------------------------------------------------------- #
# Heatmaps
# --------------------------------------------------------------------------- #
st.markdown("#### Heatmaps")
if teams:
    cols = st.columns(len(teams))
    for col, team in zip(cols, teams):
        fig = heatmap_fig(analytics.team_points(stats, team), f"{team}", bins)
        col.pyplot(fig, use_container_width=True)
        plt.close(fig)
else:
    fig = heatmap_fig(analytics.team_points(stats), "All players", bins)
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

# --------------------------------------------------------------------------- #
# Formation / average positions
# --------------------------------------------------------------------------- #
st.markdown("#### Average positions (formation)")
presence = st.slider("Min presence (% of frames)", 5, 80, 25,
                     help="Hide flickery ghost tracks seen in only a few frames.")
min_fr = max(3, int(presence / 100 * n_frames))
positions = analytics.average_positions(stats, min_frames=min_fr)
if positions:
    fig = formation_fig(positions, "Average position per tracked player")
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)
    st.caption(f"Showing {len(positions)} of {n_players} tracks (seen in "
               f"≥ {min_fr} frames). Labels are jersey numbers (or `t#` track "
               "ids until jersey OCR is enabled).")
else:
    st.caption(f"No players seen in ≥ {min_fr} frames — lower the presence "
               "threshold.")

# --------------------------------------------------------------------------- #
# Shape metrics + territory
# --------------------------------------------------------------------------- #
st.markdown("#### Team shape & territory")
shape_cols = st.columns(max(1, len(teams)))
terr = analytics.territory(stats, home_attacks_positive_x=home_lr)
for col, team in zip(shape_cols, teams or []):
    summ = analytics.team_shape_summary(stats, team)
    with col:
        st.markdown(f"**{team}**")
        if summ:
            m1, m2, m3 = st.columns(3)
            m1.metric("Compactness", f"{summ['compactness']:.1f}")
            m2.metric("Depth", f"{summ['spread_length']:.1f}")
            m3.metric("Width", f"{summ['spread_width']:.1f}")
            st.caption(
                f"Centroid ({summ['centroid_x']:.0f}, {summ['centroid_y']:.0f}) · "
                f"avg {summ['avg_players']:.1f} players/frame"
            )
        t = terr.get(team, {})
        if t:
            st.caption(
                f"Territory — def {t['defensive']*100:.0f}% · "
                f"mid {t['middle']*100:.0f}% · att {t['attacking']*100:.0f}%"
            )
            st.progress(t["attacking"], text="Time in attacking third")

st.caption("Lower **compactness** = tighter block. **Depth** = front-to-back "
           "spread, **Width** = side-to-side spread (normalised 0–100 units).")

# --------------------------------------------------------------------------- #
# Per-player heatmap
# --------------------------------------------------------------------------- #
st.divider()
st.markdown("#### Per-player heatmap")
player_ids = sorted(analytics.collect_player_points(stats).keys())
if player_ids:
    pid = st.selectbox("Player", player_ids)
    fig = heatmap_fig(analytics.player_points(stats, pid), pid, bins)
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)
    st.caption("Per-player views depend on stable tracking IDs — reliable in "
               "clips now, and across a full match once jersey-number OCR is on "
               "(Phase 4).")

# --------------------------------------------------------------------------- #
# AI analyst over the spatial findings
# --------------------------------------------------------------------------- #
st.divider()
st.markdown("#### Ask the analyst about positioning")
st.caption("Answered locally by the Ollama model from the computed spatial "
           "findings above — nothing leaves this machine.")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
SPATIAL_SYSTEM = (
    "You are Kickoff Pulse, an elite, level-headed soccer analyst. You are given "
    "computed SPATIAL findings from computer-vision tracking of one match (team "
    "heatmaps, average positions, shape metrics, territory). Answer using ONLY "
    "that data. Be concise and specific — cite the numbers (compactness, "
    "depth/width, territory %, busiest zones). If the data is uncalibrated image "
    "space, don't overclaim precise distances. If it's too thin, say so. "
    "2-5 sentences unless asked for more."
)

# Context the analyst reads: the spatial digest + a one-line score if available.
spatial_ctx = analytics.spatial_summary(stats, home_attacks_positive_x=home_lr)
try:
    import stats as S  # the dashboard's event log, for match-aware answers
    _ev = S.load_events()
    if _ev:
        _h, _a = S.team_stats(_ev, "Home"), S.team_stats(_ev, "Away")
        spatial_ctx += (f"\nFrom the event log: score Home {_h['Goals']}-"
                        f"{_a['Goals']} Away, shots H{_h['Shots']}/A{_a['Shots']}.")
except Exception:
    pass

with st.expander("What the analyst sees"):
    st.code(spatial_ctx)

SHAPE_PROMPTS = {
    "Describe the shape": "Describe each team's shape — compact or stretched, high or deep.",
    "Where was the play?": "Which areas did each team occupy most, and what does that imply?",
    "Who controlled territory?": "Which team controlled field position and territory, and how?",
    "Tactical read": "Give a short tactical read from the positioning and heatmaps.",
}

if "kp_shape_chat" not in st.session_state:
    st.session_state.kp_shape_chat = []


def _ask_spatial(question: str, context: str) -> str:
    payload = {
        "model": OLLAMA_MODEL, "stream": False, "options": {"temperature": 0.3},
        "messages": [
            {"role": "system", "content": SPATIAL_SYSTEM},
            {"role": "user",
             "content": f"SPATIAL DATA:\n{context}\n\nQUESTION: {question}"},
        ],
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


pending = None
pcols = st.columns(len(SHAPE_PROMPTS))
for (label, q), col in zip(SHAPE_PROMPTS.items(), pcols):
    if col.button(label, width="stretch", key=f"shape_{label}"):
        pending = q
typed = st.chat_input("Ask about shape, heatmaps, positioning…")
if typed:
    pending = typed

if pending:
    st.session_state.kp_shape_chat.append(("user", pending))
    try:
        with st.spinner("Analyzing positioning…"):
            answer = _ask_spatial(pending, spatial_ctx)
    except Exception as exc:
        answer = (f"Couldn't reach the local model ({exc}). Start Ollama "
                  "(`ollama serve`) and pull the model (`ollama pull llama3.2`).")
    st.session_state.kp_shape_chat.append(("ai", answer))

for role, text in st.session_state.kp_shape_chat:
    with st.chat_message("user" if role == "user" else "assistant"):
        st.markdown(text)

if st.session_state.kp_shape_chat and st.button("Clear", key="shape_clear"):
    st.session_state.kp_shape_chat = []
    st.rerun()
