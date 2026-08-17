#!/usr/bin/env python3
"""
Kickoff Pulse — momentum graph renderer.

Draws the decaying-momentum series (see insights.momentum_series) as a clean
area chart for the report: Home pressure shaded above the zero line (Pulse
Blue), Away pressure below it (red), with goals marked as vertical lines. The
same event log that feeds the chart also carries bridged vision passes, so the
curve blends the audio play-by-play and the CV layer.
"""

from __future__ import annotations

import insights as IN

HOME_HEX = "#1E7BFF"   # Pulse Blue (brand)
AWAY_HEX = "#DC2626"   # red
INK_HEX = "#111827"
MUTED_HEX = "#6B7280"
HOME_RGB = (30, 123, 255)
HOME_FILL = (216, 232, 255)
AWAY_RGB = (220, 38, 38)
AWAY_FILL = (252, 222, 222)
INK_RGB = (17, 24, 39)
MUTED_RGB = (107, 114, 128)
LINE_RGB = (222, 226, 230)


def render(events, path, width_px=1040, height_px=420, dpi=130) -> str | None:
    """Render the momentum chart to `path`. Returns the path, or None if there
    is nothing to plot (so callers can simply skip the section)."""
    rows = IN.momentum_series(events)
    if len(rows) < 2:
        return None

    try:
        import matplotlib
        matplotlib.use("Agg")  # headless: no display needed
        import matplotlib.pyplot as plt
    except Exception:
        return _render_with_pillow(events, rows, path, width_px, height_px)

    xs = [r["minute"] for r in rows]
    ys = [r["momentum"] for r in rows]

    fig, ax = plt.subplots(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    ax.fill_between(xs, ys, 0, where=[y >= 0 for y in ys], color=HOME_HEX,
                    alpha=0.85, interpolate=True, linewidth=0)
    ax.fill_between(xs, ys, 0, where=[y <= 0 for y in ys], color=AWAY_HEX,
                    alpha=0.85, interpolate=True, linewidth=0)
    ax.axhline(0, color=MUTED_HEX, linewidth=1)

    # Goals as vertical guide lines, coloured by the scoring side.
    for e in events:
        if e.get("status") == "denied":
            continue
        if e.get("action") == "goal" or (e.get("result") or "").lower() == "scored":
            minute = IN.parse_minute(e, 0.0)
            col = HOME_HEX if e.get("team") == "Home" else AWAY_HEX
            ax.axvline(minute, color=col, linestyle=":", linewidth=1.3, alpha=0.9)

    top = max(max(ys), 0.1)
    bot = min(min(ys), -0.1)
    ax.set_ylim(bot * 1.15, top * 1.15)
    ax.set_xlim(min(xs), max(xs))
    ax.text(0.006, 0.94, "HOME pressure", transform=ax.transAxes, color=HOME_HEX,
            fontsize=8, fontweight="bold", va="top")
    ax.text(0.006, 0.06, "AWAY pressure", transform=ax.transAxes, color=AWAY_HEX,
            fontsize=8, fontweight="bold", va="bottom")
    ax.set_xlabel("Match minute", fontsize=8, color=MUTED_HEX)
    ax.set_yticks([])
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(MUTED_HEX)
    ax.tick_params(axis="x", colors=MUTED_HEX, labelsize=8)
    fig.tight_layout(pad=0.6)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def _render_with_pillow(events, rows, path, width_px, height_px) -> str:
    """Lightweight fallback for CI and lean installs without matplotlib."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width_px, height_px), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    left, right, top_pad, bottom = 62, 20, 28, 46
    plot_w = max(width_px - left - right, 1)
    plot_h = max(height_px - top_pad - bottom, 1)
    xs = [r["minute"] for r in rows]
    ys = [r["momentum"] for r in rows]
    min_x, max_x = min(xs), max(xs)
    top = max(max(ys), 0.1)
    bot = min(min(ys), -0.1)
    top *= 1.15
    bot *= 1.15

    def x_pos(value):
        span = max(max_x - min_x, 0.001)
        return left + (value - min_x) / span * plot_w

    def y_pos(value):
        span = max(top - bot, 0.001)
        return top_pad + (top - value) / span * plot_h

    zero_y = y_pos(0)
    draw.rectangle((left, top_pad, width_px - right, height_px - bottom),
                   outline=LINE_RGB)
    draw.line((left, zero_y, width_px - right, zero_y), fill=MUTED_RGB, width=2)

    points = [(x_pos(x), y_pos(y)) for x, y in zip(xs, ys)]
    for idx in range(len(points) - 1):
        x1, y1 = points[idx]
        x2, y2 = points[idx + 1]
        avg = (ys[idx] + ys[idx + 1]) / 2
        fill = HOME_FILL if avg >= 0 else AWAY_FILL
        draw.polygon([(x1, zero_y), (x1, y1), (x2, y2), (x2, zero_y)],
                     fill=fill)
    draw.line(points, fill=INK_RGB, width=3, joint="curve")

    for e in events:
        if e.get("status") == "denied":
            continue
        if e.get("action") == "goal" or (e.get("result") or "").lower() == "scored":
            x = x_pos(IN.parse_minute(e, 0.0))
            color = HOME_RGB if e.get("team") == "Home" else AWAY_RGB
            draw.line((x, top_pad, x, height_px - bottom), fill=color, width=2)

    draw.text((left + 6, top_pad + 7), "HOME pressure", fill=HOME_RGB,
              font=font)
    draw.text((left + 6, height_px - bottom - 18), "AWAY pressure",
              fill=AWAY_RGB, font=font)
    draw.text((left, height_px - 28), "Match minute", fill=MUTED_RGB,
              font=font)
    draw.text((left, height_px - 15), f"{min_x:.0f}", fill=MUTED_RGB,
              font=font)
    end_label = f"{max_x:.0f}"
    try:
        label_w = draw.textlength(end_label, font=font)
    except AttributeError:
        label_w = font.getlength(end_label)
    draw.text((width_px - right - label_w, height_px - 15), end_label,
              fill=MUTED_RGB, font=font)

    img.save(path)
    return path
