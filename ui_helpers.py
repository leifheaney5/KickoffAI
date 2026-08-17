#!/usr/bin/env python3
"""
Shared UI building blocks for the Kickoff Pulse pages.

These render helpers and small formatters used to live inside dashboard.py when
the whole app was one page. They now live here so the Live Match, Match Setup,
Audio & Mic and Post-Match pages can each import the pieces they need.
"""

import html
import os
import time

import pandas as pd
import requests
import streamlit as st

import brand
import control
import icons as IC
import screen_recorder
import stats as S

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

HOME, AWAY = brand.HOME, brand.AWAY
NAVY, PULSE, SIGNAL = brand.NAVY, brand.PULSE, brand.SIGNAL


# --------------------------------------------------------------------------- #
# Small render helpers
# --------------------------------------------------------------------------- #
def mic_svg(active: bool) -> str:
    color = "#34d399" if active else "#5b6e92"
    glow = "filter:drop-shadow(0 0 6px rgba(52,211,153,.9))" if active else ""
    return (
        f"<svg width='18' height='18' viewBox='0 0 24 24' fill='none' "
        f"stroke='{color}' stroke-width='2' stroke-linecap='round' "
        f"stroke-linejoin='round' style='{glow}'>"
        f"<rect x='9' y='3' width='6' height='11' rx='3'/>"
        f"<path d='M5 11a7 7 0 0 0 14 0'/><path d='M12 18v3'/></svg>"
    )


def eye_svg(active: bool) -> str:
    """The Eye's counterpart to mic_svg — same size, weight and glow language."""
    color = "#34d399" if active else "#5b6e92"
    glow = "filter:drop-shadow(0 0 6px rgba(52,211,153,.9))" if active else ""
    return (
        f"<svg width='18' height='18' viewBox='0 0 24 24' fill='none' "
        f"stroke='{color}' stroke-width='2' stroke-linecap='round' "
        f"stroke-linejoin='round' style='{glow}'>"
        f"<path d='M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z'/>"
        f"<circle cx='12' cy='12' r='3'/></svg>"
    )


def event_time(e):
    return e.get("match_time") or (e.get("timestamp", "")[11:19])


def event_summary(e):
    parts = [p for p in [
        e.get("action"), e.get("result"),
        (f"by {e['player']}" if e.get("player") else None),
        (f"@ {e['location']}" if e.get("location") else None),
    ] if p]
    return " · ".join(parts) if parts else f'“{e.get("raw_text", "")}”'


def team_chip(team) -> str:
    if team == "Home":
        return ("<span class='team-chip' style='color:var(--c-home2);"
                "border-color:rgba(30,123,255,.4);background:rgba(30,123,255,.12)'>HOME</span>")
    if team == "Away":
        return ("<span class='team-chip' style='color:#FF6B6B;"
                "border-color:rgba(220,38,38,.45);background:rgba(220,38,38,.12)'>AWAY</span>")
    return ("<span class='team-chip' style='color:var(--c-muted);"
            "border-color:var(--border);background:rgba(255,255,255,.05)'>—</span>")


def roster_df(lineups, team) -> pd.DataFrame:
    """A two-column (Number, Name) editor frame for a team's roster."""
    rows = [{"Number": str(p.get("number") or ""), "Name": str(p.get("name") or "")}
            for p in control.roster_for(lineups, team)]
    if not rows:
        rows = [{"Number": "", "Name": ""}]  # one empty row to type into
    return pd.DataFrame(rows, columns=["Number", "Name"])


def df_to_players(df) -> list:
    """Convert an edited roster frame back to [{number, name}], dropping blanks."""
    players = []
    for _, r in df.iterrows():
        num = str(r.get("Number") or "").strip()
        name = str(r.get("Name") or "").strip()
        if num or name:
            players.append({"number": num, "name": name})
    return players


def cmp_row(label: str, h, a) -> str:
    """Wireframe-style diverging comparison row: value | bar | value."""
    h = h or 0
    a = a or 0
    total = h + a
    hp = (h / total * 100) if total else 0
    ap = (a / total * 100) if total else 0
    return (
        f"<div class='cmp-row'>"
        f"<span class='cmp-val home'>{h}</span>"
        f"<div class='cmp-bars'>"
        f"<div class='cmp-left'><div class='cmp-fill home' style='width:{hp:.0f}%'></div></div>"
        f"<span class='cmp-mid'>{label}</span>"
        f"<div class='cmp-right'><div class='cmp-fill away' style='width:{ap:.0f}%'></div></div>"
        f"</div>"
        f"<span class='cmp-val away'>{a}</span>"
        f"</div>"
    )


def render_voice_guide():
    """Collapsible guide for phrasing voice events clearly."""
    with st.expander("Voice guide - phrasing that logs cleanly", expanded=False):
        st.markdown(
            """
**Best order:** `Home/Away` -> `number/player` -> `action` -> `result` -> `location`

Say the side and shirt number before the event whenever you can.

**Clean examples**

- `Home number 10 shot on target from the box`
- `Away number 4 yellow card`
- `Home number 7 completed pass in midfield`
- `Away number 1 save`
- `Home corner kick`
- `Away number 9 offside`
- `Home substitution number 12 comes on`

**Use these action words**

`goal`, `shot`, `save`, `pass`, `tackle`, `foul`, `yellow card`, `red card`,
`corner`, `offside`, `cross`, `dribble`, `clearance`, `interception`,
`substitution`

**Useful result words**

`scored`, `on target`, `blocked`, `missed`, `saved`, `complete`,
`incomplete`, `won`, `lost`

Keep each phrase to one event. Pause briefly between events so the tracker does
not merge them into one transcript.
            """
        )


def render_audio_chunking_controls(state):
    defaults = control.DEFAULT["audio_chunking"]
    chunking = {**defaults, **(state.get("audio_chunking") or {})}

    with st.expander("Audio chunking"):
        p0, p1, _ = st.columns([1, 1, 2])
        if p0.button("Conservative", width="stretch"):
            state["audio_chunking"] = dict(defaults)
            control.save_control(state)
            st.rerun()
        if p1.button("Quick commentary", width="stretch"):
            state["audio_chunking"] = {
                "phrase_time_limit": 6.0,
                "pause_threshold": 0.55,
                "min_phrase_sec": 0.3,
                "post_speech_padding": 0.1,
            }
            control.save_control(state)
            st.rerun()

        c1, c2 = st.columns(2)
        phrase_time = c1.slider(
            "Phrase limit", 2.0, 20.0,
            float(chunking.get("phrase_time_limit", defaults["phrase_time_limit"])),
            step=0.5, help="Maximum seconds captured for one spoken event.")
        pause = c2.slider(
            "Pause to end phrase", 0.25, 2.0,
            float(chunking.get("pause_threshold", defaults["pause_threshold"])),
            step=0.05, help="Silence length that closes the current phrase.")
        c3, c4 = st.columns(2)
        min_phrase = c3.slider(
            "Minimum phrase", 0.1, 2.0,
            float(chunking.get("min_phrase_sec", defaults["min_phrase_sec"])),
            step=0.05, help="Shorter clips are ignored before Whisper runs.")
        padding = c4.slider(
            "Post-speech padding", 0.0, 1.0,
            float(chunking.get("post_speech_padding",
                               defaults["post_speech_padding"])),
            step=0.05, help="Non-speaking audio kept around each phrase.")

        updated = {
            "phrase_time_limit": phrase_time,
            "pause_threshold": pause,
            "min_phrase_sec": min_phrase,
            "post_speech_padding": padding,
        }
        if updated != chunking:
            state["audio_chunking"] = updated
            control.save_control(state)


def render_mic_calibration(state):
    status = control.load_status()
    energy = status.get("last_energy")
    threshold = status.get("energy_threshold")
    ignored = status.get("last_ignored_reason") or "none"
    gate = status.get("noise_gate", state.get("noise_gate", control.DEFAULT_NOISE_GATE))

    st.markdown(brand.section("Mic calibration"), unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Last energy", "—" if energy is None else f"{energy:.0f}")
    m2.metric("Threshold", "—" if threshold is None else f"{threshold:.0f}")
    m3.metric("Gate", f"{int(gate)}/100")
    m4.metric("Ignored", ignored)

    cal = state.get("calibration_test") or {}
    armed = bool(cal.get("armed"))
    b1, b2 = st.columns([1, 3], vertical_alignment="center")
    if b1.button("Arm test phrase" if not armed else "Waiting...",
                 disabled=armed, width="stretch"):
        state["calibration_test"] = {
            "armed": True,
            "requested_at": time.time(),
            "last_result_at": cal.get("last_result_at"),
        }
        control.save_control(state)
        st.rerun()
    with b2:
        st.caption("Say: Home number 10 shot on target from the box")

    result = status.get("calibration_test") or {}
    if result:
        ok = "passed" if result.get("ok") else f"blocked: {result.get('reason')}"
        st.caption(
            f"Last test {ok} · energy {result.get('energy') or '—'} · "
            f"latency {result.get('latency_ms') or '—'} ms"
        )
        st.caption(f"Raw: {result.get('raw_text') or '—'}")
        st.caption(f"Corrected: {result.get('corrected_text') or '—'}")
        if result.get("suggested_text"):
            st.caption(f"Parsed: {result['suggested_text']}")


def ai_summary(events):
    """Ask the local model to write a short, neutral match summary."""
    home = S.team_stats(events, "Home")
    away = S.team_stats(events, "Away")
    facts = (
        f"Final score: Home {home['Goals']} - {away['Goals']} Away. "
        f"Shots {home['Shots']}-{away['Shots']} (on target "
        f"{home['On Target']}-{away['On Target']}). "
        f"Fouls {home['Fouls']}-{away['Fouls']}. "
        f"Cards: Home {home['Yellow Cards']}Y/{home['Red Cards']}R, "
        f"Away {away['Yellow Cards']}Y/{away['Red Cards']}R. "
        f"Saves {home['Saves']}-{away['Saves']}. "
        f"Corners {home['Corners']}-{away['Corners']}."
    )
    payload = {
        "model": OLLAMA_MODEL, "stream": False, "options": {"temperature": 0.4},
        "messages": [
            {"role": "system", "content":
             "You are a concise soccer reporter. Write a neutral 2-4 sentence "
             "summary of the match from the stats given. Plain text, no markdown."},
            {"role": "user", "content": facts},
        ],
    }
    resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


# --------------------------------------------------------------------------- #
# Live fragments (auto-refresh every second)
# --------------------------------------------------------------------------- #
# The Eye's health maps onto the same dot vocabulary as the mic chip.
_EYE_DOT = {"ok": "rec", "starting": "paused", "paused": "paused",
            "stale": "warn", "down": "off"}


def vision_chips() -> str:
    """Chips describing the Eye. Empty string when vision isn't this match's job."""
    import vision_runner

    st_v = vision_runner.status()
    dot = _EYE_DOT.get(st_v["health"], "off")
    label = vision_runner.health_label(st_v)

    chips = [
        f"<div class='kp-chip'>{eye_svg(st_v['health'] == 'ok')}"
        f"<span class='dot {dot}'></span><span class='v'>{label}</span></div>"
    ]
    if st_v["running"]:
        home, away = st_v["possession_home"], st_v["possession_away"]
        chips += [
            f"<div class='kp-chip'><span class='l'>FPS</span>"
            f"<span class='v mono'>{st_v['fps']:.1f}</span></div>",
            f"<div class='kp-chip'><span class='l'>Ball</span>"
            f"<span class='v mono'>{st_v['ball_rate'] * 100:.0f}%</span></div>",
            f"<div class='kp-chip'><span class='l'>Poss</span>"
            f"<span class='v mono'>{home:.0f}/{away:.0f}</span></div>",
            f"<div class='kp-chip'><span class='l'>Passes</span>"
            f"<span class='v'>{st_v['passes']}</span></div>",
        ]
        if st_v["reconnects"]:
            chips.append(
                f"<div class='kp-chip'><span class='l'>Drops</span>"
                f"<span class='v'>{st_v['reconnects']} recovered</span></div>")
    return "".join(chips)


def voice_chips() -> str:
    """Chips describing the mic tracker (the Ear)."""
    status = control.load_status()
    paused = control.load_control().get("paused", False)
    online = control.tracker_online(status)
    if not online:
        dot, label, active = "off", "Offline", False
    elif paused:
        dot, label, active = "paused", "Paused", False
    else:
        dot, label, active = "rec", "Recording", True

    rec = control.fmt_clock(control.record_seconds(status))
    session = (control.fmt_clock(time.time() - status["session_start"])
               if status.get("session_start") else "00:00")
    events_n = status.get("events", len(S.load_events()))
    heard = status.get("last_heard") or "—"

    # Only surface the processing backlog when there is one — keeps the bar clean
    # in the common case where the worker is keeping up with capture.
    queued = status.get("queued", 0)
    dropped = status.get("dropped", 0)
    backlog_chip = ""
    if active and (queued or dropped):
        parts = []
        if queued:
            parts.append(f"{queued} queued")
        if dropped:
            parts.append(f"{dropped} dropped")
        backlog_chip = (
            f"<div class='kp-chip'><span class='l'>Backlog</span>"
            f"<span class='v'>{' · '.join(parts)}</span></div>")

    return (
        f"<div class='kp-chip'>{mic_svg(active)}<span class='dot {dot}'></span>"
        f"<span class='v'>{label}</span></div>"
        f"<div class='kp-chip'><span class='l'>Rec</span>"
        f"<span class='v mono'>{rec}</span></div>"
        f"<div class='kp-chip'><span class='l'>Session</span>"
        f"<span class='v mono'>{session}</span></div>"
        f"<div class='kp-chip'><span class='l'>Events</span>"
        f"<span class='v'>{events_n}</span></div>"
        f"{backlog_chip}"
        f"<div class='kp-chip heard'><span class='l'>Heard</span>"
        f"<span class='kp-heard'>{heard}</span></div>")


def render_status_chips():
    """The live status bar, showing only the ingest paths this match uses.

    Previously this was mic-only, which left a vision-first match with a bar
    that said "Offline" while the Eye was happily analysing.
    """
    state = control.load_control()
    parts = []
    if control.uses_vision(state):
        parts.append(vision_chips())
    if control.uses_voice(state):
        parts.append(voice_chips())
    if not parts:                       # defensive: an unknown mode
        parts.append(voice_chips())

    st.markdown(f"<div class='kp-status'>{''.join(parts)}</div>",
                unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Match notes (typed or spoken)
# --------------------------------------------------------------------------- #
def note_badge(note) -> str:
    """A small source tag so typed and spoken notes are told apart at a glance."""
    written = control.note_source(note) == "written"
    label = "WRITTEN" if written else "VOICE"
    color = "var(--c-muted)" if written else "#34d399"
    return (f"<span style='font-family:var(--font-disp);font-size:.6rem;"
            f"letter-spacing:.14em;color:{color};font-weight:600'>{label}</span>")


def render_note_composer(state, key="note_compose"):
    """Text box + Add button for writing a match note.

    Kept out of any auto-refreshing fragment: a 1s rerun would wipe half-typed
    text. Returns True when a note was saved.
    """
    text = st.text_area(
        "Write a note", key=key, height=90, label_visibility="collapsed",
        placeholder="Type an observation — a tactical read, an injury, "
                    "something to review later…")
    c1, c2 = st.columns([1, 3], vertical_alignment="center")
    saved = False
    if c1.button("Add note", type="primary", width="stretch",
                 key=f"{key}_add", disabled=not text.strip()):
        try:
            control.add_written_note(text, state)
            saved = True
        except ValueError as exc:
            st.warning(str(exc))
    with c2:
        main_clk, added, _half = control.clock_label(state["timer"])
        stamp = f"{main_clk}{(' ' + added) if added else ''}"
        st.caption(f"Saved against the match clock ({stamp}) and included in the "
                   "post-match report.")
    if saved:
        # Clear the box for the next note, then redraw the list.
        st.session_state.pop(key, None)
        st.rerun()
    return saved


def render_notes_list(limit=30, key_prefix="note"):
    """The match notes, newest first, with their source and a delete button."""
    notes = control.load_notes()
    if not notes:
        st.caption("No notes yet.")
        return
    shown = list(reversed(notes))[:limit]
    for n in shown:
        nc1, nc2 = st.columns([12, 1], vertical_alignment="center")
        nc1.markdown(
            f"<div class='kp-feed'><div class='body'><div class='top'>"
            f"<span class='t'>{n.get('match_time') or ''}</span>"
            f"&nbsp;&nbsp;{note_badge(n)}</div>"
            f"<div class='sum'>{html.escape(n.get('text', ''))}</div>"
            f"</div></div>", unsafe_allow_html=True)
        if nc2.button("✕", key=f"{key_prefix}_del_{n['timestamp']}",
                      help="Delete note"):
            control.delete_note(n["timestamp"])
            st.rerun()
    if len(notes) > limit:
        st.caption(f"Showing the {limit} most recent of {len(notes)} notes. "
                   "All of them appear in the report and on Insights.")


# --------------------------------------------------------------------------- #
# The Eye (vision runner) — controls + live frame
# --------------------------------------------------------------------------- #
def render_eye_controls(state=None, key_prefix="eye"):
    """Start / Pause / Stop for the vision runner.

    Must be called OUTSIDE an auto-refreshing fragment: a fragment that reruns
    every second can swallow a click before it registers. Returns the runner
    status dict so callers can render around it without polling twice.
    """
    import vision_runner

    state = control.load_control() if state is None else state
    st_v = vision_runner.status()
    supported, reason = vision_runner.is_supported()
    ready = control.feed_ready(state)

    cols = st.columns([1, 1, 1, 2.6], vertical_alignment="center")
    if not st_v["running"]:
        if cols[0].button("▶  Start Eye", type="primary", width="stretch",
                          disabled=not (supported and ready),
                          key=f"{key_prefix}_start"):
            res = vision_runner.start(state)
            if res.get("ok"):
                st.toast(f"Eye started on {res['source']}.")
            else:
                st.session_state[f"{key_prefix}_error"] = res
            st.rerun()
    elif st_v["paused"]:
        if cols[0].button("▶  Resume", type="primary", width="stretch",
                          key=f"{key_prefix}_resume"):
            vision_runner.resume()
            st.rerun()
    else:
        if cols[0].button("⏸  Pause", width="stretch", key=f"{key_prefix}_pause"):
            vision_runner.pause()
            st.rerun()

    if cols[1].button("⯀  Stop Eye", width="stretch",
                      disabled=not st_v["running"], key=f"{key_prefix}_stop"):
        with st.spinner("Saving the final checkpoint…"):
            res = vision_runner.stop()
        st.toast("Eye stopped." if res.get("ok") else res.get("error", ""))
        st.rerun()

    with cols[3]:
        if not supported:
            st.caption(reason)
        elif not ready:
            st.caption("No feed configured — set one up on **Camera & Feed**.")
        elif st_v["running"]:
            when = control.fmt_clock(st_v["elapsed"])
            st.caption(f"Analysing {st_v['source_label']} · {when} elapsed"
                       + (f" · match {st_v['match_time']}"
                          if st_v["match_time"] else ""))
        else:
            st.caption(f"Ready to analyse {control.feed_label(state)}.")

    err = st.session_state.get(f"{key_prefix}_error")
    if err:
        st.error(err.get("error", "Could not start the Eye."))
        if err.get("detail"):
            with st.expander("Runner output"):
                st.code(err["detail"])

    if st_v["ended_unexpectedly"] and not st_v["running"]:
        st.warning("The Eye stopped on its own. The stream may have ended or "
                   "dropped for good.")
        with st.expander("Runner output"):
            st.code(vision_runner.log_tail() or "(no output)")
    elif st_v["health"] == "stale":
        st.warning("The Eye is running but hasn't produced a frame recently — "
                   "the feed may have stalled.")

    return st_v


def render_eye_frame(height=None):
    """The latest annotated frame the runner wrote. Safe inside a fragment."""
    import vision_runner

    st_v = vision_runner.status()
    path = vision_runner.SNAPSHOT_FILE
    if not os.path.exists(path):
        if st_v["running"]:
            st.info("Waiting for the first annotated frame…")
        else:
            st.caption("No frame yet — start the Eye to see the live view.")
        return

    age = vision_runner.snapshot_age()
    stamp = time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(path)))
    caption = f"Latest annotated frame · {stamp}"
    if age is not None and age > 15 and st_v["running"] and not st_v["paused"]:
        caption += f" · {int(age)}s old"
    st.image(path, width="stretch", caption=caption)


def render_scoreboard():
    events = S.load_events()
    state = control.load_control()
    home = S.team_stats(events, "Home")
    away = S.team_stats(events, "Away")
    main_clk, added, half = control.clock_label(state["timer"])

    teams = state.get("teams", {})
    home_name = teams.get("home", {}).get("name", "").strip() or "Home"
    away_name = teams.get("away", {}).get("name", "").strip() or "Away"

    added_html = f"<span class='added'> {added}</span>" if added else ""
    half_lbl = (half + ("  ·  ADDED TIME" if added else "")).upper()
    st.markdown(
        f"<div class='panel scoreboard'>"
        f"<div class='sb-side sb-home'>"
        f"<div class='sb-team'>{home_name}</div>"
        f"<div class='sb-score'>{home['Goals']}</div>"
        f"</div>"
        f"<div class='sb-center'>"
        f"<div class='sb-half'>{half_lbl}</div>"
        f"<div class='sb-clock'>{main_clk}{added_html}</div>"
        f"</div>"
        f"<div class='sb-side sb-away'>"
        f"<div class='sb-team'>{away_name}</div>"
        f"<div class='sb-score'>{away['Goals']}</div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True)


def render_stats_feed():
    events = S.load_events()
    state = control.load_control()
    home = S.team_stats(events, "Home")
    away = S.team_stats(events, "Away")
    players = S.player_stats(events)

    teams = state.get("teams", {})
    home_label = teams.get("home", {}).get("name", "").strip().upper() or "HOME"
    away_label = teams.get("away", {}).get("name", "").strip().upper() or "AWAY"

    col_stats, col_feed = st.columns([1.05, 1], gap="large")

    # ---- Team comparison (head-to-head) -------------------------------- #
    with col_stats:
        st.markdown(brand.section("Team comparison", "TEAM STATS"), unsafe_allow_html=True)
        legend = (
            f"<div class='cmp-legend'>"
            f"<span><span class='cmp-dot home'></span>{home_label}</span>"
            f"<span><span class='cmp-dot away'></span>{away_label}</span>"
            f"</div>"
        )
        rows = "".join(cmp_row(k, home[k], away[k]) for k in S.STAT_KEYS)
        st.markdown(
            f"<div class='panel'>{legend}"
            f"<div class='cmp-rows'>{rows}</div>"
            f"</div>",
            unsafe_allow_html=True)

    # ---- Live feed ----------------------------------------------------- #
    with col_feed:
        st.markdown(brand.section("Live feed", "REAL-TIME"), unsafe_allow_html=True)
        if not events:
            st.info("No events yet. Start narrating the match into your mic.")
        else:
            feed_items = "".join(
                f"<div class='feed-item'>{IC.badge_html(e, 32)}"
                f"<div class='feed-body'>"
                f"<div class='feed-meta'>"
                f"<span class='feed-type'>{IC.KIND_LABEL.get(IC.event_kind(e), 'Event')}</span>"
                f"{team_chip(e.get('team'))}"
                f"<span class='feed-time'>{event_time(e)}</span>"
                f"</div>"
                f"<div class='feed-desc'>{event_summary(e)}</div>"
                f"</div></div>"
                for e in reversed(events[-20:])
            )
            st.markdown(f"<div class='panel' style='padding:12px'>"
                        f"<div class='feed-list'>{feed_items}</div></div>",
                        unsafe_allow_html=True)

    # ---- Players ------------------------------------------------------- #
    st.write("")
    st.markdown(brand.section("Player stats", "PER PLAYER"), unsafe_allow_html=True)
    if players:
        cols = ["Team"] + S.STAT_KEYS
        df = pd.DataFrame(
            {p: {c: v.get(c) for c in cols} for p, v in players.items()}).T
        df = df.reindex(columns=cols)
        df.index.name = "Player"
        df = df.sort_values(["Goals", "Shots"], ascending=False)
        st.dataframe(df, width="stretch")

        pick = st.session_state.get("spotlight")
        if pick and pick in players:
            p = players[pick]
            accent = HOME if p["Team"] == "Home" else AWAY
            keys = ["Goals", "Shots", "On Target", "Saves", "Tackles", "Fouls",
                    "Yellow Cards", "Red Cards"]
            chips = "".join(
                f"<div class='row'><span>{k}</span><span class='v'>{p[k]}</span></div>"
                for k in keys)
            st.markdown(
                f"<div class='kp-card' style='border-top:3px solid {accent};margin-top:10px'>"
                f"<div class='card-title'>{pick} "
                f"<span style='color:{accent}'>· {p['Team'] or '—'}</span></div>"
                f"{chips}</div>", unsafe_allow_html=True)
    else:
        st.caption("No player-tagged events yet. Say a name or number, e.g. "
                   "“number 6 with a tackle”.")

    # ---- Substitutions ------------------------------------------------- #
    subs = [e for e in events if e.get("action") == "substitution"]
    if subs:
        st.write("")
        st.markdown(brand.section("Substitutions", "SUBS"), unsafe_allow_html=True)
        sub_items = "".join(
            f"<div class='feed-item'>{IC.badge_html(e, 30)}"
            f"<div class='feed-body'>"
            f"<div class='feed-meta'>{team_chip(e.get('team'))}"
            f"<span class='feed-time'>{event_time(e)}</span></div>"
            f"<div class='feed-desc'>{e.get('player') or 'unknown'} comes on</div>"
            f"</div></div>"
            for e in subs
        )
        st.markdown(f"<div class='panel' style='padding:12px'>"
                    f"<div class='feed-list'>{sub_items}</div></div>",
                    unsafe_allow_html=True)

    with st.expander("Raw event log"):
        if events:
            st.dataframe(pd.DataFrame(events), width="stretch", height=280)
        else:
            st.write("Empty.")


def render_capture_indicator():
    """Live REC chip — its own fragment so the elapsed time ticks each second."""
    rs = screen_recorder.status()
    if rs["recording"]:
        st.markdown(
            f"<span style='display:inline-flex;align-items:center;gap:8px'>"
            f"<span class='dot rec'></span>"
            f"<span style='color:{SIGNAL};font-weight:600;letter-spacing:.04em'>REC</span> "
            f"<span class='mono'>{control.fmt_clock(rs['elapsed'])}</span> · "
            f"{os.path.basename(rs['file'] or '')}</span>",
            unsafe_allow_html=True)
    elif rs.get("ended_unexpectedly"):
        st.caption("Last recording stopped on its own — check Screen Recording "
                   "permission for your terminal.")
    else:
        st.caption("Captures the screen + your mic to a file in recordings/.")


def render_match_title(state, events):
    """Centered logo + editable match title — the shared page hero."""
    st.markdown(
        f"<div style='text-align:center; margin:2px 0 6px'>"
        f"<img class='kp-reveal' src='{brand.logo_data_uri('dark', 300)}' "
        f"style='width:300px; max-width:78%; animation-delay:.12s'/></div>",
        unsafe_allow_html=True)

    match_name = (state.get("match_name") or "").strip()
    with st.popover(match_name or "✎  Name this match"):
        st.caption("Name this match / session")
        new_name = st.text_input(
            "Match name", value=match_name,
            placeholder="e.g. Eagles vs Hawks — Jun 7",
            label_visibility="collapsed", key="match_name_input")
        s1, s2 = st.columns(2)
        if s1.button("Save name", type="primary", width="stretch"):
            state["match_name"] = new_name.strip()
            control.save_control(state)
            st.rerun()
        if match_name and s2.button("Clear", width="stretch"):
            state["match_name"] = ""
            control.save_control(state)
            st.rerun()
    st.markdown(
        f"<div style='text-align:center; color:#9fb6dd; font-size:.85rem; margin-top:2px'>"
        f"Live match tracker · click the title to rename · {len(events)} events logged"
        f"</div>", unsafe_allow_html=True)


def live_fragment(fn):
    """Run a render function as a 1s auto-refreshing fragment when available."""
    if hasattr(st, "fragment"):
        st.fragment(run_every=1.0)(fn)()
    else:
        fn()
