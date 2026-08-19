#!/usr/bin/env python3
"""
Kickoff Pulse — per-player share packs.

Clips without a way to send them stay in a folder, and a development trend
nobody sees is a chart for one person. This is the step that gets both to the
player: a portrait card sized for messaging, and a zip holding their clips.

Scoped to one player on purpose. A pack contains that player's own line and
nothing else — no squad table, no other children's names — because the thing
being handed to a parent should be about their child and only their child.

Card rendering reuses the existing Pillow treatment from share_image.py so the
visual language stays one system.
"""

from __future__ import annotations

import io
import os
import re
import time
import zipfile

import stats as S


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", str(text or "")).strip("-").lower() or "player"


def player_line(events, player: str) -> dict:
    """One player's stat block for this match, or {} if they did nothing."""
    return (S.player_stats(events) or {}).get(player, {})


def clips_for(player: str, clip_results) -> list:
    """The clips featuring this player, from an extract() result or a plan."""
    out = []
    for c in (clip_results or {}).get("clips", clip_results or []):
        if not isinstance(c, dict):
            continue
        if (c.get("player") or "").strip() == (player or "").strip():
            out.append(c)
    return out


# --------------------------------------------------------------------------- #
# The card
# --------------------------------------------------------------------------- #
CARD_METRICS = ("Goals", "Shots", "On Target", "Saves", "Tackles", "Fouls")


def render_card(player: str, line: dict, match_name: str = "", clock: str = "",
                team: str = "", season_form: dict = None, path: str = None):
    """A portrait card for one player, as PNG bytes (and optionally to `path`)."""
    from PIL import Image, ImageDraw

    import brand
    from share_image import _gradient
    from timeline_image import _font

    # Only what the player actually did, so the card never pads itself with a
    # column of zeros.
    shown = [(m, line.get(m, 0)) for m in CARD_METRICS if line.get(m)]
    if not shown:
        shown = [("Appearances", 1)]

    # Height follows the content. A fixed portrait sized for a six-stat forward
    # leaves a defender with two tackles looking like a broken layout.
    W = 1080
    head = 400 + (48 if match_name else 0) + (48 if clock else 0)
    body = 84 * len(shown) + (70 if (season_form
                                     and season_form.get("matches", 0) > 1) else 0)
    H = max(720, head + body + 200)
    img = _gradient(W, H, (7, 26, 61), (11, 47, 116))
    d = ImageDraw.Draw(img)

    accent = brand.HOME if team == "Home" else brand.AWAY if team == "Away" \
        else brand.SIGNAL

    f_kicker = _font(30, bold=True)
    f_name = _font(96, bold=True)
    f_sub = _font(34)
    f_metric = _font(40)
    f_value = _font(64, bold=True)

    y = 90
    d.text((70, y), "PLAYER REPORT", font=f_kicker, fill=(159, 182, 221))
    y += 58
    d.text((70, y), str(player), font=f_name, fill=(234, 241, 255))
    y += 118
    if match_name:
        d.text((70, y), match_name, font=f_sub, fill=(159, 182, 221))
        y += 48
    if clock:
        d.text((70, y), clock, font=f_sub, fill=(126, 149, 191))
        y += 48

    d.line([(70, y + 18), (W - 70, y + 18)], fill=(255, 255, 255, 40), width=2)
    y += 60

    for metric, value in shown:
        d.text((70, y + 8), metric, font=f_metric, fill=(159, 182, 221))
        vw = d.textlength(str(value), font=f_value)
        d.text((W - 70 - vw, y), str(value), font=f_value, fill=(234, 241, 255))
        y += 84

    if season_form and season_form.get("matches", 0) > 1:
        arrow = {"up": "▲", "down": "▼", "flat": "="}.get(season_form["trend"], "=")
        d.text((70, y + 20),
               f"Season {season_form['metric'].lower()}: "
               f"{season_form['recent']} recent vs {season_form['baseline']} "
               f"average  {arrow}",
               font=f_sub, fill=(159, 182, 221))

    # Accent rule at the foot, tying the card to the team colour.
    d.rectangle([(0, H - 14), (W, H)], fill=tuple(
        int(accent.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)))
    d.text((70, H - 90), "Kickoff Pulse", font=f_sub, fill=(126, 149, 191))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    if path:
        with open(path, "wb") as fh:
            fh.write(data)
    return data


# --------------------------------------------------------------------------- #
# The zip
# --------------------------------------------------------------------------- #
def build_pack(player: str, events, clip_results=None, match_name: str = "",
               clock: str = "", season_form: dict = None,
               out_dir: str = "exports") -> dict:
    """Assemble one player's card and clips into a single zip.

    Returns {path, clips, card_bytes}. Contains only this player's material.
    """
    line = player_line(events, player)
    card = render_card(player, line, match_name=match_name, clock=clock,
                       team=line.get("Team", ""), season_form=season_form)
    mine = clips_for(player, clip_results)

    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d")
    base = f"{_slug(match_name) or 'match'}_{_slug(player)}_{stamp}"
    zip_path = os.path.join(out_dir, f"{base}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{_slug(player)}_card.png", card)
        for c in mine:
            src = c.get("path")
            if src and os.path.exists(src):
                z.write(src, os.path.join("clips", os.path.basename(src)))
        z.writestr("summary.txt", _summary_text(player, line, match_name, clock,
                                                mine, season_form))
    return {"path": zip_path, "clips": mine, "card_bytes": card, "line": line}


def _summary_text(player, line, match_name, clock, clips_, form) -> str:
    lines = [f"{player} — {match_name or 'Match'}", ""]
    if clock:
        lines.append(f"Match time: {clock}")
    if line.get("Team"):
        lines.append(f"Team: {line['Team']}")
    lines.append("")
    for m in CARD_METRICS:
        if line.get(m):
            lines.append(f"  {m}: {line[m]}")
    if form and form.get("matches", 0) > 1:
        lines += ["", f"Season {form['metric'].lower()}: {form['recent']} in "
                      f"recent matches vs {form['baseline']} average "
                      f"({form['trend']})."]
    if clips_:
        lines += ["", "Clips included:"]
        lines += [f"  {c.get('match_time', '')}  {c.get('label', '')}"
                  for c in clips_]
    lines += ["", "Generated by Kickoff Pulse."]
    return "\n".join(lines)
