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


def render(events, path, width_px=1040, height_px=420, dpi=130) -> str | None:
    """Render the momentum chart to `path`. Returns the path, or None if there
    is nothing to plot (so callers can simply skip the section)."""
    rows = IN.momentum_series(events)
    if len(rows) < 2:
        return None

    import matplotlib
    matplotlib.use("Agg")  # headless: no display needed
    import matplotlib.pyplot as plt

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
