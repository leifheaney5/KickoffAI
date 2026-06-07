#!/usr/bin/env python3
"""
Kickoff Pulse — timeline image renderer.

Draws the match event log as a clean vertical timeline PNG using Pillow:
a vertical rail with a coloured icon badge per event (team-coloured ring),
the match-clock time, and a short description. Used by the Timeline page's
"export image" button and embedded into the PDF report.
"""

import os

from PIL import Image, ImageDraw, ImageFont

import icons as IC

# Layout (pixels)
WIDTH = 1040
PAD = 36
RAIL_X = 92
BADGE_R = 19
ROW_H = 74
HEADER_H = 132

INK = (17, 24, 39)        # brand Dark Text
MUTED = (107, 114, 128)
RAIL = (224, 228, 232)
BG = (255, 255, 255)


def _rgb(hexv: str):
    hexv = hexv.lstrip("#")
    return tuple(int(hexv[i:i + 2], 16) for i in (0, 2, 4))


def _font(size, bold=False):
    win = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    candidates = (
        # Windows (Inter if installed, then Segoe UI / Arial bold)
        [os.path.join(win, "Inter-Bold.ttf"), os.path.join(win, "seguisb.ttf"),
         os.path.join(win, "segoeuib.ttf"), os.path.join(win, "arialbd.ttf"),
         # macOS
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/System/Library/Fonts/HelveticaNeue.ttc"]
        if bold else
        [os.path.join(win, "Inter-Regular.ttf"), os.path.join(win, "segoeui.ttf"),
         os.path.join(win, "arial.ttf"),
         "/System/Library/Fonts/Supplemental/Arial.ttf",
         "/System/Library/Fonts/HelveticaNeue.ttc"]
    ) + ["/Library/Fonts/Arial.ttf"]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _event_time(e):
    if e.get("match_time"):
        return str(e["match_time"])
    ts = e.get("timestamp", "")
    return ts[11:19] if len(ts) >= 19 else ts


def _summary(e):
    parts = [p for p in [e.get("action"), e.get("result")] if p]
    head = " / ".join(parts) if parts else (e.get("raw_text") or "event")
    return head


def _detail(e):
    bits = []
    if e.get("player"):
        bits.append(str(e["player"]))
    if e.get("location"):
        bits.append("@ " + str(e["location"]))
    if e.get("team"):
        bits.append(e["team"])
    return "  ·  ".join(bits)


def _draw_glyph(draw, kind, cx, cy, R):
    """Draw the white glyph for a category, centred on (cx, cy)."""
    w = (255, 255, 255)
    if kind == "goal":
        draw.ellipse([cx - R * 0.55, cy - R * 0.55, cx + R * 0.55, cy + R * 0.55], fill=w)
    elif kind in ("yellow", "red"):
        draw.rounded_rectangle([cx - R * 0.3, cy - R * 0.52, cx + R * 0.3, cy + R * 0.52],
                               radius=2, fill=w)
    elif kind == "sub":
        draw.line([cx - R * 0.5, cy - R * 0.28, cx + R * 0.35, cy - R * 0.28], fill=w, width=2)
        draw.polygon([(cx + R * 0.5, cy - R * 0.28), (cx + R * 0.2, cy - R * 0.5),
                      (cx + R * 0.2, cy - R * 0.06)], fill=w)
        draw.line([cx + R * 0.5, cy + R * 0.28, cx - R * 0.35, cy + R * 0.28], fill=w, width=2)
        draw.polygon([(cx - R * 0.5, cy + R * 0.28), (cx - R * 0.2, cy + R * 0.06),
                      (cx - R * 0.2, cy + R * 0.5)], fill=w)
    elif kind == "save":
        draw.polygon([(cx, cy - R * 0.6), (cx + R * 0.55, cy - R * 0.3),
                      (cx + R * 0.55, cy + R * 0.2), (cx, cy + R * 0.62),
                      (cx - R * 0.55, cy + R * 0.2), (cx - R * 0.55, cy - R * 0.3)], fill=w)
    elif kind == "shot":
        draw.ellipse([cx - R * 0.55, cy - R * 0.55, cx + R * 0.55, cy + R * 0.55],
                     outline=w, width=2)
        draw.ellipse([cx - R * 0.16, cy - R * 0.16, cx + R * 0.16, cy + R * 0.16], fill=w)
    elif kind == "foul":
        draw.line([cx - R * 0.45, cy - R * 0.45, cx + R * 0.45, cy + R * 0.45], fill=w, width=2)
        draw.line([cx + R * 0.45, cy - R * 0.45, cx - R * 0.45, cy + R * 0.45], fill=w, width=2)
    elif kind in ("corner", "offside"):
        draw.line([cx - R * 0.35, cy - R * 0.55, cx - R * 0.35, cy + R * 0.55], fill=w, width=2)
        flag = [(cx - R * 0.35, cy - R * 0.5), (cx + R * 0.5, cy - R * 0.18),
                (cx - R * 0.35, cy + R * 0.14)]
        if kind == "corner":
            draw.polygon(flag, fill=w)
        else:
            draw.line(flag + [flag[0]], fill=w, width=2, joint="curve")
    elif kind in ("pass", "tackle"):
        draw.line([cx - R * 0.5, cy, cx + R * 0.25, cy], fill=w, width=2)
        draw.polygon([(cx + R * 0.5, cy), (cx + R * 0.2, cy - R * 0.25),
                      (cx + R * 0.2, cy + R * 0.25)], fill=w)
    else:
        draw.ellipse([cx - R * 0.28, cy - R * 0.28, cx + R * 0.28, cy + R * 0.28], fill=w)


def render(events, score=(0, 0), clock="", title="Match Timeline", path=None):
    """Render the timeline to a PNG and return its path (or an in-memory image)."""
    events = list(events)
    n = max(len(events), 1)
    height = HEADER_H + n * ROW_H + PAD

    img = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(img)

    f_title = _font(30, bold=True)
    f_sub = _font(16)
    f_time = _font(16, bold=True)
    f_main = _font(18, bold=True)
    f_detail = _font(14)

    # Header
    draw.text((PAD, PAD - 6), "KICKOFF PULSE", font=f_title, fill=_rgb(IC.HOME_COLOR))
    draw.text((PAD, PAD + 32), title, font=f_sub, fill=MUTED)
    score_txt = f"HOME {score[0]} - {score[1]} AWAY"
    if clock:
        score_txt += f"     |     {clock}"
    draw.text((PAD, PAD + 58), score_txt, font=f_main, fill=INK)
    draw.line([PAD, HEADER_H - 14, WIDTH - PAD, HEADER_H - 14], fill=RAIL, width=2)

    if not events:
        draw.text((PAD, HEADER_H + 10), "No events logged.", font=f_sub, fill=MUTED)
        return _finish(img, path)

    # Vertical rail
    top = HEADER_H + ROW_H // 2
    bottom = HEADER_H + (n - 1) * ROW_H + ROW_H // 2
    draw.line([RAIL_X, top, RAIL_X, bottom], fill=RAIL, width=3)

    for i, e in enumerate(events):
        cy = HEADER_H + i * ROW_H + ROW_H // 2
        kind = IC.event_kind(e)
        # Badge: team-coloured ring + category fill
        ring = _rgb(IC.team_color(e.get("team")))
        fill = _rgb(IC.kind_color(kind))
        draw.ellipse([RAIL_X - BADGE_R - 3, cy - BADGE_R - 3,
                      RAIL_X + BADGE_R + 3, cy + BADGE_R + 3], fill=ring)
        draw.ellipse([RAIL_X - BADGE_R, cy - BADGE_R,
                      RAIL_X + BADGE_R, cy + BADGE_R], fill=fill)
        _draw_glyph(draw, kind, RAIL_X, cy, BADGE_R)

        # Text — time, then the category label placed just after it
        tx = RAIL_X + BADGE_R + 22
        time_txt = _event_time(e)
        draw.text((tx, cy - 22), time_txt, font=f_time, fill=MUTED)
        time_w = draw.textlength(time_txt, font=f_time)
        kind_lbl = IC.KIND_LABEL.get(kind, "Event")
        draw.text((tx + time_w + 16, cy - 23), kind_lbl, font=f_main, fill=fill)
        summ = _summary(e)
        detail = _detail(e)
        line2 = summ + (("   —   " + detail) if detail else "")
        draw.text((tx, cy + 2), line2[:96], font=f_detail, fill=INK)

    return _finish(img, path)


def _finish(img, path):
    if path:
        img.save(path, "PNG")
        return path
    return img


def render_to_bytes(events, **kw):
    import io
    img = render(events, path=None, **kw)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
