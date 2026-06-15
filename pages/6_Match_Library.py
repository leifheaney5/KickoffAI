#!/usr/bin/env python3
"""
Kickoff Pulse — Match Library page.

Browse every finalized match and its artifacts (reports, data, audio, images,
video) from the local database, preview them inline, and export a match as a
single zip. The DB indexes; files live under library/<slug>/ (see library.py).
"""

import os
import sys
from datetime import datetime

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brand           # noqa: E402
import db              # noqa: E402
import embed           # noqa: E402
import library         # noqa: E402

st.set_page_config(page_title=f"{brand.NAME} — Match Library",
                   page_icon=brand.LOGO_TRANSPARENT, layout="wide")
st.markdown(brand.global_css(), unsafe_allow_html=True)

# Artifact display groups: (heading, the kinds it contains).
_DOWNLOAD_KINDS = {
    "report_pdf": ("Match report (PDF)", "application/pdf"),
    "report_txt": ("Match report (text)", "text/plain"),
    "events_csv": ("Events (CSV)", "text/csv"),
    "team_csv": ("Team stats (CSV)", "text/csv"),
    "player_csv": ("Player stats (CSV)", "text/csv"),
    "data_json": ("Data (JSON)", "application/json"),
}
_IMAGE_KINDS = {"timeline_png", "image"}


# --------------------------------------------------------------------------- #
# Data access (extract plain dicts inside the session to avoid detached rows)
# --------------------------------------------------------------------------- #
def load_matches():
    db.init_db()
    out = []
    with db.session() as s:
        rows = (s.query(db.Match)
                .order_by(db.Match.played_on.desc(), db.Match.created_at.desc())
                .all())
        for m in rows:
            out.append({
                "id": str(m.id), "slug": m.slug, "name": m.name,
                "played_on": m.played_on, "home_team": m.home_team,
                "away_team": m.away_team, "home_score": m.home_score,
                "away_score": m.away_score, "summary": m.summary,
                "n_media": len(m.media), "n_events": len(m.events),
            })
    return out


def load_detail(slug):
    db.init_db()
    with db.session() as s:
        m = s.query(db.Match).filter_by(slug=slug).first()
        if m is None:
            return None
        return {
            "slug": m.slug, "name": m.name, "played_on": m.played_on,
            "home_team": m.home_team, "away_team": m.away_team,
            "home_score": m.home_score, "away_score": m.away_score,
            "summary": m.summary, "n_events": len(m.events),
            "media": [{"kind": mf.kind, "label": mf.label, "path": mf.path,
                       "abs": os.path.join(library.LIBRARY_ROOT, mf.path),
                       "bytes": mf.bytes} for mf in m.media],
        }


def _fmt_date(d):
    return d.isoformat() if d else "—"


# --------------------------------------------------------------------------- #
# Detail view
# --------------------------------------------------------------------------- #
def render_detail(slug):
    d = load_detail(slug)
    if d is None:
        st.warning("That match is no longer in the library.")
        st.session_state.pop("lib_selected", None)
        return

    if st.button("←  Back to library"):
        st.session_state.pop("lib_selected", None)
        st.rerun()

    home = d["home_team"] or "Home"
    away = d["away_team"] or "Away"
    st.markdown(brand.page_header("LIBRARY", d["name"]), unsafe_allow_html=True)
    st.markdown(
        f"<div class='panel scoreboard'>"
        f"<div class='sb-side sb-home'><div class='sb-team'>{home}</div>"
        f"<div class='sb-score'>{d['home_score']}</div></div>"
        f"<div class='sb-center'><div class='sb-half'>{_fmt_date(d['played_on'])}</div>"
        f"<div class='sb-clock' style='font-size:1.1rem'>{d['n_events']} events</div></div>"
        f"<div class='sb-side sb-away'><div class='sb-team'>{away}</div>"
        f"<div class='sb-score'>{d['away_score']}</div></div></div>",
        unsafe_allow_html=True)

    if d["summary"]:
        st.caption(d["summary"])

    # Export match (zip of the whole folder + manifest).
    manifest = {
        "slug": d["slug"], "name": d["name"],
        "played_on": d["played_on"], "home_team": home, "away_team": away,
        "score": [d["home_score"], d["away_score"]], "summary": d["summary"],
        "files": [{"kind": m["kind"], "path": m["path"], "label": m["label"],
                   "bytes": m["bytes"]} for m in d["media"]],
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    }
    st.download_button(
        "⬇  Export match (.zip)", data=library.export_zip(d["slug"], manifest),
        file_name=f"{d['slug']}.zip", mime="application/zip", type="primary")

    media = d["media"]
    if not media:
        st.info("No artifacts stored for this match.")
        return

    by_kind = {}
    for m in media:
        by_kind.setdefault(m["kind"], []).append(m)

    # Reports & data — download buttons.
    docs = [m for m in media if m["kind"] in _DOWNLOAD_KINDS]
    if docs:
        st.markdown(brand.section("Reports & data"), unsafe_allow_html=True)
        cols = st.columns(2)
        for i, m in enumerate(docs):
            label, mime = _DOWNLOAD_KINDS[m["kind"]]
            with cols[i % 2]:
                if os.path.exists(m["abs"]):
                    with open(m["abs"], "rb") as fh:
                        st.download_button(
                            f"{label} · {m['bytes']//1024 or 1} KB", fh.read(),
                            file_name=os.path.basename(m["path"]), mime=mime,
                            width="stretch", key=f"dl_{m['path']}")
                else:
                    st.caption(f"Missing: {os.path.basename(m['path'])}")

    # Images.
    imgs = [m for m in media if m["kind"] in _IMAGE_KINDS]
    if imgs:
        st.markdown(brand.section("Images"), unsafe_allow_html=True)
        for m in imgs:
            if os.path.exists(m["abs"]):
                st.image(m["abs"], caption=m["label"], width="stretch")

    # Audio notes.
    audio = by_kind.get("audio_note", [])
    if audio:
        st.markdown(brand.section("Voice notes"), unsafe_allow_html=True)
        for m in audio:
            st.caption(m["label"])
            if os.path.exists(m["abs"]):
                st.audio(m["abs"])

    # Video.
    vids = by_kind.get("video", [])
    if vids:
        st.markdown(brand.section("Video"), unsafe_allow_html=True)
        for m in vids:
            if os.path.exists(m["abs"]):
                st.video(m["abs"])

    # Danger zone — delete the match (DB row + files).
    with st.expander("Delete this match"):
        st.caption("Permanently removes the match's database record and every "
                   "file in its library folder. This cannot be undone.")
        confirm = st.checkbox("I understand, delete it", key=f"del_ok_{slug}")
        if st.button("Delete match", disabled=not confirm,
                     key=f"del_btn_{slug}"):
            library.delete_match(slug)
            st.session_state.pop("lib_selected", None)
            st.rerun()


# --------------------------------------------------------------------------- #
# List view
# --------------------------------------------------------------------------- #
def render_list():
    match_name = "Match Library"
    st.markdown(brand.page_header("LIBRARY", match_name), unsafe_allow_html=True)

    matches = load_matches()

    # Import legacy reports/ artifacts into the library.
    with st.expander("Import existing reports"):
        st.caption("Scan the reports/ folder and import any past matches that "
                   "aren't in the library yet.")
        if st.button("Import from reports/"):
            import backfill
            with st.spinner("Importing…"):
                added = backfill.backfill_reports()
            if added:
                st.success(f"Imported {len(added)} match(es).")
                st.rerun()
            else:
                st.info("Nothing new to import.")

    if not matches:
        st.info("No matches in the library yet. Finalize a match from the "
                "dashboard's export panel to archive it here, or import past "
                "reports above.")
        return

    semantic = False
    if embed.is_enabled():
        sc1, sc2 = st.columns([4, 1], vertical_alignment="center")
        q = sc1.text_input(
            "Search", placeholder="Search by name, team, or meaning…",
            label_visibility="collapsed")
        semantic = sc2.toggle("AI search", value=False,
                              help="Rank by meaning using semantic embeddings "
                              "instead of exact text matching.")
    else:
        q = st.text_input("Search", placeholder="Filter by match or team name…",
                          label_visibility="collapsed")

    if q and semantic:
        results = embed.search(q, k=len(matches))
        if results is None:
            st.warning("Semantic search is unavailable (is Ollama running?). "
                       "Showing all matches.")
        else:
            order = {mid: i for i, (mid, _) in enumerate(results)}
            scores = {mid: sc for mid, sc in results}
            ranked = [m for m in matches if m["id"] in order]
            ranked.sort(key=lambda m: order[m["id"]])
            for m in ranked:
                m["_score"] = scores.get(m["id"])
            matches = ranked
    elif q:
        ql = q.lower()
        matches = [m for m in matches if ql in (m["name"] or "").lower()
                   or ql in (m["home_team"] or "").lower()
                   or ql in (m["away_team"] or "").lower()]

    st.caption(f"{len(matches)} match{'es' if len(matches) != 1 else ''}")
    for m in matches:
        c1, c2, c3 = st.columns([5, 2, 1.4], vertical_alignment="center")
        with c1:
            score_chip = ""
            if m.get("_score") is not None:
                score_chip = (f" · <span style='color:#2BE7FF'>"
                              f"{m['_score']*100:.0f}% match</span>")
            st.markdown(
                f"<div style='font-family:var(--font-disp);font-weight:700;"
                f"font-size:1.05rem;color:#fff'>{m['name']}</div>"
                f"<div style='color:#9fb6dd;font-size:.85rem'>"
                f"{_fmt_date(m['played_on'])} · {m['n_media']} files · "
                f"{m['n_events']} events{score_chip}</div>",
                unsafe_allow_html=True)
        with c2:
            st.markdown(
                f"<div style='text-align:center;font-family:var(--font-mono);"
                f"font-size:1.2rem;color:#fff'>{m['home_score']}–{m['away_score']}"
                f"</div>", unsafe_allow_html=True)
        with c3:
            if st.button("Open", key=f"open_{m['slug']}", width="stretch"):
                st.session_state["lib_selected"] = m["slug"]
                st.rerun()
        st.divider()


# --------------------------------------------------------------------------- #
# Route
# --------------------------------------------------------------------------- #
if st.session_state.get("lib_selected"):
    render_detail(st.session_state["lib_selected"])
else:
    render_list()
