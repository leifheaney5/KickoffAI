#!/usr/bin/env python3
"""
Kickoff Pulse — mobile share card.

Renders a portrait (1080x1350) match summary image — scoreline, possession, and
the headline team stats — sized for texting / sharing from a phone. Reuses the
font + colour helpers from the timeline renderer for a consistent look.
"""

import io
import time

from PIL import Image, ImageDraw

import stats as S
from timeline_image import _font

WIDTH, HEIGHT = 1080, 1350
PAD = 72

HOME_RGB = (30, 123, 255)    # Pulse Blue
AWAY_RGB = (220, 38, 38)     # red
NAVY_TOP = (7, 22, 52)
NAVY_BOT = (12, 47, 116)
WHITE = (255, 255, 255)
MUTED = (159, 182, 221)
TRACK = (30, 44, 74)
FAINT = (42, 60, 96)


def _gradient(w, h, top, bot):
    img = Image.new("RGB", (w, h), top)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        draw.line([(0, y), (w, y)],
                  fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return img


def render_summary_card(events, score=None, clock="", match_name="", path=None):
    """Render the portrait summary card; return its path or the PIL image."""
    events = list(events)
    home = S.team_stats(events, "Home")
    away = S.team_stats(events, "Away")
    if score is None:
        score = (home["Goals"], away["Goals"])
    hp, ap = S.possession(home, away)

    img = _gradient(WIDTH, HEIGHT, NAVY_TOP, NAVY_BOT)
    draw = ImageDraw.Draw(img)

    f_brand = _font(42, bold=True)
    f_sub = _font(26)
    f_team = _font(32, bold=True)
    f_score = _font(150, bold=True)
    f_clock = _font(28, bold=True)
    f_stat = _font(36, bold=True)
    f_lbl = _font(27)
    f_foot = _font(22)

    # Header
    draw.text((PAD, PAD), "KICKOFF PULSE", font=f_brand, fill=WHITE)
    if match_name:
        draw.text((PAD, PAD + 54), match_name[:42], font=f_sub, fill=MUTED)

    # Scoreline
    cy = 380
    qx = WIDTH * 0.27
    draw.text((qx, cy - 96), "HOME", font=f_team, fill=HOME_RGB, anchor="mm")
    draw.text((WIDTH - qx, cy - 96), "AWAY", font=f_team, fill=AWAY_RGB, anchor="mm")
    draw.text((qx, cy), str(score[0]), font=f_score, fill=HOME_RGB, anchor="mm")
    draw.text((WIDTH - qx, cy), str(score[1]), font=f_score, fill=AWAY_RGB, anchor="mm")
    draw.text((WIDTH / 2, cy), "-", font=f_score, fill=WHITE, anchor="mm")
    if clock:
        draw.text((WIDTH / 2, cy + 120), clock, font=f_clock, fill=MUTED, anchor="mm")

    # Possession bar
    by = 600
    bx0, bx1, bh = PAD, WIDTH - PAD, 48
    draw.text((WIDTH / 2, by - 28), "POSSESSION", font=f_lbl, fill=MUTED, anchor="mm")
    hw = int((bx1 - bx0) * hp / 100)
    draw.rounded_rectangle([bx0, by, bx1, by + bh], radius=14, fill=TRACK)
    if hw > 0:
        draw.rectangle([bx0, by, bx0 + hw, by + bh], fill=HOME_RGB)
    if hw < (bx1 - bx0):
        draw.rectangle([bx0 + hw, by, bx1, by + bh], fill=AWAY_RGB)
    draw.text((bx0 + 18, by + bh / 2), f"{hp:.0f}%", font=f_lbl, fill=WHITE, anchor="lm")
    draw.text((bx1 - 18, by + bh / 2), f"{ap:.0f}%", font=f_lbl, fill=WHITE, anchor="rm")

    # Headline stat rows (goals live in the scoreline)
    rows = [
        ("Shots", home["Shots"], away["Shots"]),
        ("On Target", home["On Target"], away["On Target"]),
        ("Saves", home["Saves"], away["Saves"]),
        ("Tackles", home["Tackles"], away["Tackles"]),
        ("Fouls", home["Fouls"], away["Fouls"]),
        ("Corners", home["Corners"], away["Corners"]),
        ("Cards", f"{home['Yellow Cards']}Y/{home['Red Cards']}R",
                  f"{away['Yellow Cards']}Y/{away['Red Cards']}R"),
        ("Passes", home["Passes"], away["Passes"]),
    ]
    ry = by + bh + 78
    gap = 66
    for label, hv, av in rows:
        draw.text((PAD, ry), str(hv), font=f_stat, fill=HOME_RGB, anchor="lm")
        draw.text((WIDTH / 2, ry), label, font=f_lbl, fill=MUTED, anchor="mm")
        draw.text((WIDTH - PAD, ry), str(av), font=f_stat, fill=AWAY_RGB, anchor="rm")
        draw.line([PAD, ry + gap / 2, WIDTH - PAD, ry + gap / 2], fill=FAINT, width=1)
        ry += gap

    # Footer
    draw.text((PAD, HEIGHT - PAD + 6),
              f"Generated {time.strftime('%Y-%m-%d %H:%M')}  ·  {len(events)} events",
              font=f_foot, fill=MUTED)

    if path:
        img.save(path, "PNG")
        return path
    return img


def render_to_bytes(events, **kw):
    img = render_summary_card(events, path=None, **kw)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
