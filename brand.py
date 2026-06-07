#!/usr/bin/env python3
"""
Kickoff Pulse — shared brand kit.

A single source of truth for the brand palette, fonts, logo assets, and the
header treatment, so the dashboard, timeline page, and any future screens stay
on-brand. Mirrors branding/kickoff-pulse-branding-guide.md.
"""

import base64
import os
from functools import lru_cache

# --------------------------------------------------------------------------- #
# Palette (from the branding guide)
# --------------------------------------------------------------------------- #
NAVY = "#071A3D"      # Primary Navy — headers, nav, logos, text
PULSE = "#1E7BFF"     # Pulse Blue — buttons, links, primary actions
SIGNAL = "#4DA3FF"    # Signal Blue — hover, charts, audio indicators
BG = "#F8FAFC"        # App background
INK = "#111827"       # Dark text
MUTED = "#6B7280"     # Secondary text

# Team identities: Home aligns to the brand blue, Away stays a clear red so the
# two sides always read as distinct.
HOME = PULSE
AWAY = "#DC2626"

NAME = "Kickoff Pulse"
TAGLINE = "AI-powered soccer intelligence — the pulse of the match."

FONT_STACK = "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"

_HERE = os.path.dirname(os.path.abspath(__file__))
LOGO_TRANSPARENT = os.path.join(_HERE, "branding",
                                "kickoff-pulse-logo-transparent-bg.png")
LOGO_WHITE_BG = os.path.join(_HERE, "branding",
                             "kickoff-pulse-logo-white-bg.png")


@lru_cache(maxsize=8)
def logo_data_uri(which: str = "transparent", max_h: int = 160) -> str:
    """Return a base64 data-URI of the logo, cropped to content and scaled.

    `which`: "transparent" (white ball, for dark surfaces) or "white" (dark ball
    on a white card). Cached so we only encode once per size.
    """
    from PIL import Image

    path = LOGO_WHITE_BG if which == "white" else LOGO_TRANSPARENT
    if not os.path.exists(path):
        return ""
    im = Image.open(path).convert("RGBA")
    bbox = im.getbbox()           # tight crop around non-transparent content
    if bbox:
        im = im.crop(bbox)
    if im.height > max_h:
        w = round(im.width * max_h / im.height)
        im = im.resize((w, max_h), Image.LANCZOS)

    import io
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


@lru_cache(maxsize=2)
def logo_pil_white(pad: int = 24):
    """Cropped PIL image of the white-background logo (dark ball) for print/PDF.

    Returns None if the asset is missing. The white-bg art has no transparency,
    so we crop by the non-white bounding box.
    """
    if not os.path.exists(LOGO_WHITE_BG):
        return None
    from PIL import Image
    import numpy as np

    im = Image.open(LOGO_WHITE_BG).convert("RGB")
    a = np.array(im)
    nonwhite = (a < 245).any(axis=2)
    ys, xs = np.where(nonwhite)
    if len(xs) == 0:
        return im
    box = (max(int(xs.min()) - pad, 0), max(int(ys.min()) - pad, 0),
           min(int(xs.max()) + pad, im.width), min(int(ys.max()) + pad, im.height))
    im = im.crop(box)
    if im.width > 700:        # plenty sharp for a print header; keeps PDFs lean
        im = im.resize((700, round(im.height * 700 / im.width)), Image.LANCZOS)
    return im


def global_css() -> str:
    """Brand-wide CSS: Inter font, palette, rounded cards/buttons, navy hero."""
    return f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
      html, body, [class*="css"], .stMarkdown, .stApp {{
        font-family: {FONT_STACK}; }}
      h1, h2, h3, h4 {{ font-weight: 800; letter-spacing: -0.02em; color: {NAVY}; }}
      .block-container {{ padding-top: 1.4rem; max-width: 1200px; }}

      /* Buttons — rounded, brand blue, subtle shadow */
      .stButton > button, .stDownloadButton > button {{
        border-radius: 12px !important; font-weight: 600 !important;
        transition: all .15s ease; }}
      .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{
        background: {PULSE} !important; border-color: {PULSE} !important; }}
      .stButton > button[kind="primary"]:hover {{
        background: {SIGNAL} !important; border-color: {SIGNAL} !important; }}

      /* Navy brand hero */
      .kp-hero {{ display:flex; align-items:center; gap:20px;
        background: linear-gradient(120deg, {NAVY} 0%, #0b2a5e 100%);
        border-radius: 16px; padding: 16px 24px; margin-bottom: 14px;
        box-shadow: 0 4px 12px rgba(7,26,61,.18); }}
      .kp-hero img {{ height: 60px; display:block; }}
      .kp-hero .kp-tag {{ color:#cdddf7; font-size:.92rem; font-weight:500;
        margin-left:auto; text-align:right; max-width:46%; }}
    </style>
    """


def header_html(tagline: str = TAGLINE) -> str:
    """A navy hero banner with the white-ball logo (reads on the navy)."""
    uri = logo_data_uri("transparent", max_h=120)
    img = f"<img src='{uri}'/>" if uri else f"<h2 style='color:#fff;margin:0'>{NAME}</h2>"
    tag = f"<div class='kp-tag'>{tagline}</div>" if tagline else ""
    return f"<div class='kp-hero'>{img}{tag}</div>"
