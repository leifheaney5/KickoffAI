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

# Type system — a broadcast/sports-tech pairing (no Inter/Roboto/Arial):
#   Display : Chakra Petch  — squared techno-sport, for headings & scores
#   Body    : Sora          — geometric humanist, highly legible UI text
#   Mono    : Spline Sans Mono — distinctive tabular mono for the clock/times
FONT_DISPLAY = "'Chakra Petch', 'Bahnschrift', sans-serif"
FONT_SANS = "'Sora', 'Segoe UI', sans-serif"
FONT_MONO = "'Spline Sans Mono', ui-monospace, monospace"
FONT_STACK = FONT_SANS  # backwards-compatible alias

_HERE = os.path.dirname(os.path.abspath(__file__))
LOGO_TRANSPARENT = os.path.join(_HERE, "branding",
                                "kickoff-pulse-logo-transparent-bg.png")
LOGO_WHITE_BG = os.path.join(_HERE, "branding",
                             "kickoff-pulse-logo-white-bg.png")
# Dark-mode variant: light wordmark, for navy / blue-gradient surfaces.
LOGO_DARK = os.path.join(_HERE, "branding",
                         "kickoff-pulse-logo-darkmode.png")


@lru_cache(maxsize=8)
def logo_data_uri(which: str = "transparent", max_h: int = 160) -> str:
    """Return a base64 data-URI of the logo, cropped to content and scaled.

    `which`: "transparent" (white ball, navy wordmark), "dark" (light wordmark
    for navy/blue surfaces), or "white" (dark ball on a white card). Cached so we
    only encode once per size.
    """
    from PIL import Image

    path = {"white": LOGO_WHITE_BG, "dark": LOGO_DARK}.get(which, LOGO_TRANSPARENT)
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


# --------------------------------------------------------------------------- #
# Design system — one comprehensive stylesheet shared by every page.
# --------------------------------------------------------------------------- #
# Palette + tokens are injected via :root (small f-string); the bulk of the CSS
# is a plain string that references the var(--*) tokens, so we don't have to
# double every brace inside an f-string.
_ROOT = (
    ":root{"
    f"--fd:{FONT_DISPLAY};--fs:{FONT_SANS};--fm:{FONT_MONO};"
    f"--navy:{NAVY};--pulse:{PULSE};--signal:{SIGNAL};--home:{HOME};--away:{AWAY};"
    # sharp accents: electric cyan highlight + hot signal for live/alerts
    "--accent:#2BE7FF;--live:#FF3D6E;"
    "--txt:#eaf1ff;--muted:#9fb6dd;--muted2:#7e95bf;"
    "--glass:rgba(255,255,255,.055);--glass-2:rgba(255,255,255,.10);"
    "--glass-bd:rgba(255,255,255,.13);--shadow:0 14px 40px rgba(2,8,23,.45);}"
)

# Atmospheric background: a faint soccer-pitch line pattern layered over stadium
# light glows and a deep navy→blue gradient — depth + context, not a flat fill.
_PITCH_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1200 760'>"
    "<g fill='none' stroke='%23bcd2ff' stroke-width='2' opacity='0.5'>"
    "<circle cx='600' cy='380' r='118'/><circle cx='600' cy='380' r='4' fill='%23bcd2ff'/>"
    "<line x1='600' y1='20' x2='600' y2='740'/>"
    "<rect x='20' y='230' width='150' height='300' rx='2'/>"
    "<rect x='20' y='320' width='64' height='120' rx='2'/>"
    "<rect x='1030' y='230' width='150' height='300' rx='2'/>"
    "<rect x='1116' y='320' width='64' height='120' rx='2'/>"
    "<rect x='20' y='20' width='1160' height='720' rx='4'/></g></svg>"
)
_PITCH_URI = "data:image/svg+xml," + _PITCH_SVG.replace("#", "%23").replace("\n", "")

_BG = (
    ".stApp{background:"
    f"url(\"{_PITCH_URI}\") center 70px/1180px no-repeat,"
    "radial-gradient(900px 520px at 82% -8%, rgba(43,231,255,.16) 0%, transparent 60%),"
    "radial-gradient(800px 500px at 12% 8%, rgba(30,123,255,.20) 0%, transparent 55%),"
    "linear-gradient(165deg,#04102a 0%,#071f4d 48%,#0b2f74 100%) fixed;"
    "background-attachment:fixed;}"
)

_CSS_BODY = """
  @import url('https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=Sora:wght@400;500;600;700;800&family=Spline+Sans+Mono:wght@500;600;700&display=swap');
  html, body, [class*="css"], .stMarkdown, .stApp { font-family: var(--fs); }

  [data-testid="stHeader"] { background: transparent; }
  [data-testid="stSidebar"] { background: rgba(4,12,32,.66); backdrop-filter: blur(12px);
        border-right: 1px solid var(--glass-bd); }
  .block-container { padding-top: 1.4rem; max-width: 1180px; }

  /* One orchestrated page-load: the whole app eases in once (does not replay on
     Streamlit reruns or fragment refreshes, which keep the same .stApp node). */
  .stApp { animation: kpAppIn .7s cubic-bezier(.22,.61,.36,1) both; }
  @keyframes kpAppIn { from{opacity:0; transform:translateY(10px) scale(.995);} to{opacity:1; transform:none;} }

  /* Typography */
  h1,h2,h3,h4,h5 { color:#fff !important; font-family:var(--fd) !important;
        font-weight:700; letter-spacing:.01em; }
  .stApp, .stMarkdown, .stApp p, .stApp label, .stApp li, .stApp span { color: var(--txt); }
  [data-testid="stCaptionContainer"], .stCaption, .stCaption p { color: var(--muted) !important; }
  a { color: var(--accent) !important; }

  /* Section heading with a sharp accent chip */
  .kp-section { display:flex; align-items:center; gap:10px; margin:8px 0 10px;
        font-family:var(--fd); font-size:.82rem; font-weight:600; letter-spacing:.18em;
        text-transform:uppercase; color:#cfe0ff; }
  .kp-section::before { content:''; width:13px; height:13px; border-radius:4px;
        background:linear-gradient(135deg,var(--signal),var(--accent));
        box-shadow:0 0 14px rgba(43,231,255,.8); }

  /* Buttons */
  .stButton > button, .stDownloadButton > button {
        border-radius:12px !important; font-weight:700 !important; letter-spacing:.01em;
        border:1px solid var(--glass-bd) !important; background:var(--glass) !important;
        color:var(--txt) !important; transition:all .16s ease; }
  .stButton > button:hover, .stDownloadButton > button:hover {
        background:var(--glass-2) !important; border-color:rgba(255,255,255,.28) !important;
        transform:translateY(-1px); }
  .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
        background:linear-gradient(135deg,var(--pulse),var(--signal)) !important;
        border:none !important; color:#fff !important;
        box-shadow:0 6px 18px rgba(30,123,255,.40) !important; }
  .stButton > button[kind="primary"]:hover { filter:brightness(1.07);
        box-shadow:0 8px 22px rgba(30,123,255,.55) !important; }

  /* Dark inputs (summary textarea, selectbox on the gradient) */
  .stTextArea textarea { background:var(--glass) !important; color:var(--txt) !important;
        border:1px solid var(--glass-bd) !important; border-radius:12px !important; }
  .stTextArea textarea::placeholder { color:var(--muted2) !important; }
  div[data-baseweb="select"] > div { background:var(--glass) !important;
        border-color:var(--glass-bd) !important; border-radius:12px !important; color:var(--txt) !important; }

  /* Glass card (no entrance animation: these live inside 1s fragments) */
  .card, .kp-card { background:var(--glass); border:1px solid var(--glass-bd);
        border-radius:18px; padding:18px 20px; box-shadow:var(--shadow);
        -webkit-backdrop-filter:blur(14px); backdrop-filter:blur(14px);
        transition:border-color .18s ease, box-shadow .18s ease; }
  .kp-card:hover { border-color:rgba(255,255,255,.22); }
  .card.home { border-top:3px solid var(--home); }
  .card.away { border-top:3px solid var(--away); }
  .card-title { font-family:var(--fd); font-weight:700; font-size:1.05rem;
        margin-bottom:10px; color:#fff; }
  .row { display:flex; justify-content:space-between; padding:6px 0;
        border-bottom:1px solid rgba(255,255,255,.08); font-size:.95rem; }
  .row:last-child { border-bottom:none; }
  .row .v { font-weight:700; font-family:var(--fm); }
  /* Reveal used only on static (non-fragment) elements so it never re-plays. */
  .kp-reveal { animation:kpFade .6s cubic-bezier(.22,.61,.36,1) both; }
  @keyframes kpFade { from{opacity:0; transform:translateY(8px);} to{opacity:1;transform:none;} }

  /* Status chips */
  .kp-status { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
  .kp-chip { display:flex; align-items:center; gap:8px; padding:0 16px; min-height:40px;
        background:var(--glass); border:1px solid var(--glass-bd); border-radius:999px;
        box-shadow:var(--shadow); -webkit-backdrop-filter:blur(12px); backdrop-filter:blur(12px); }
  .kp-chip .l { font-family:var(--fd); font-size:.66rem; letter-spacing:.14em;
        text-transform:uppercase; color:var(--muted); font-weight:600; }
  .kp-chip .v { font-weight:700; color:#fff; }
  .mono { font-variant-numeric:tabular-nums; font-family:var(--fm); }
  .kp-chip.heard { flex:1; min-width:180px; }
  .kp-heard { color:var(--muted); font-style:italic; font-size:.86rem;
        overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .dot { width:11px; height:11px; border-radius:50%; display:inline-block; }
  .dot.rec { background:var(--live); animation:recpulse 1.4s infinite; }
  .dot.paused { background:#f5a623; }
  .dot.off { background:transparent; border:2px solid #5b6e92; }
  @keyframes recpulse { 0%{box-shadow:0 0 0 0 rgba(255,61,110,.6);}
        70%{box-shadow:0 0 0 10px rgba(255,61,110,0);} 100%{box-shadow:0 0 0 0 rgba(255,61,110,0);} }

  /* Scoreboard hero */
  .kp-board { display:grid; grid-template-columns:1fr 1.4fr 1fr; align-items:center; gap:8px; }
  .kp-board .side { text-align:center; }
  .kp-board .team { font-family:var(--fd); font-size:.84rem; font-weight:600;
        letter-spacing:.22em; text-transform:uppercase; }
  .kp-board .team.home { color:var(--home); } .kp-board .team.away { color:var(--away); }
  .kp-board .sc { font-family:var(--fd); font-size:4.6rem; font-weight:700; line-height:1;
        letter-spacing:-.02em; }
  .kp-board .sc.home { color:var(--home); text-shadow:0 0 30px rgba(30,123,255,.45); }
  .kp-board .sc.away { color:var(--away); text-shadow:0 0 30px rgba(220,38,38,.40); }
  .kp-board .center { text-align:center; }
  .kp-half { font-family:var(--fd); font-size:.74rem; font-weight:600; letter-spacing:.18em;
        text-transform:uppercase; color:var(--muted); margin-bottom:6px; }
  .kp-clock { font-family:var(--fm); font-size:3.1rem; font-weight:700; line-height:1;
        color:#fff; text-shadow:0 0 26px rgba(43,231,255,.25); }
  .kp-clock .added { color:var(--accent); font-size:1.2rem; font-weight:700; }

  /* Bars (possession + head-to-head) */
  .kp-bar { display:flex; height:22px; border-radius:8px; overflow:hidden;
        background:rgba(255,255,255,.07); font-size:.74rem; }
  .kp-bar .seg { display:flex; align-items:center; transition:width .4s ease;
        font-family:var(--fm); font-weight:700; min-width:0; color:#fff;
        text-shadow:0 1px 2px rgba(0,0,0,.45); }
  /* Solid team colours so the white labels stay readable and the centre
     meeting line is a clean blue↔red (no bright clashing seam). */
  .kp-bar .seg.home { background:var(--home); padding-left:10px;
        box-shadow:inset 0 -10px 14px rgba(0,0,0,.16); }
  .kp-bar .seg.away { background:var(--away); justify-content:flex-end; padding-right:10px;
        box-shadow:inset 0 -10px 14px rgba(0,0,0,.16); }
  .kp-cap { font-family:var(--fd); text-align:center; font-size:.72rem; letter-spacing:.16em;
        text-transform:uppercase; color:var(--muted); margin-top:7px; font-weight:600; }

  .h2h { margin:12px 0; }
  .h2h-top { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:5px; }
  .h2h-top .lbl { font-size:.82rem; color:var(--muted); font-weight:600; }
  .h2h-top .n { font-family:var(--fm); font-weight:700; font-size:1.04rem; color:#fff; min-width:30px; }
  .h2h-top .n.home { text-align:left; } .h2h-top .n.away { text-align:right; }

  /* Live feed (with event badges); no entrance anim — lives in a 1s fragment */
  .kp-feed { display:flex; align-items:center; gap:12px; padding:9px 12px;
        background:var(--glass); border:1px solid var(--glass-bd); border-radius:12px;
        margin-bottom:8px; transition:all .15s ease; }
  .kp-feed:hover { background:var(--glass-2); transform:translateX(3px);
        border-color:rgba(255,255,255,.24); }
  .kp-feed .body { flex:1; min-width:0; }
  .kp-feed .top { display:flex; align-items:center; gap:8px; margin-bottom:1px; }
  .kp-feed .sum { font-weight:500; color:#fff; }
  .kp-feed .meta { color:var(--muted); font-size:.82rem; }
  .chip { display:inline-block; padding:1px 10px; border-radius:999px; font-size:.7rem;
        font-weight:700; letter-spacing:.05em; color:#fff; text-transform:uppercase; }
  .t { color:var(--muted2); font-variant-numeric:tabular-nums; font-family:var(--fm);
        font-size:.82rem; }

  /* Editable match title popover trigger */
  div[data-testid="stPopover"] > div button { border:none !important; background:transparent !important;
        padding:0 !important; box-shadow:none !important; }
  div[data-testid="stPopover"] > div button p { font-family:var(--fd) !important;
        font-size:1.55rem !important; font-weight:700 !important; color:#fff !important;
        letter-spacing:.01em; }
  div[data-testid="stPopover"] > div button:hover p { color:var(--accent) !important; }

  /* Tabs */
  .stTabs [data-baseweb="tab-list"] { gap:6px; border-bottom:1px solid var(--glass-bd); }
  .stTabs [data-baseweb="tab"] { color:var(--muted); font-weight:700; }
  .stTabs [aria-selected="true"] { color:#fff !important; }
  .stTabs [data-baseweb="tab-highlight"] { background:var(--pulse) !important; }

  /* Streamlit chrome cleanup */
  [data-testid="stDecoration"] { display:none !important; }
  footer { visibility:hidden; height:0; }
  /* The collapsed-sidebar control was rendering as a stray glass box */
  [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] {
        background:transparent !important; border:none !important; box-shadow:none !important;
        -webkit-backdrop-filter:none !important; backdrop-filter:none !important; }
  [data-testid="stSidebarCollapsedControl"] button { color:#cfe0ff !important; }
  [data-testid="stSidebarNav"] a span, [data-testid="stSidebarNav"] a { color:var(--txt) !important; }
  [data-testid="stToolbar"] { background:transparent !important; }
"""


def app_css() -> str:
    """The full Kickoff Pulse design system — inject once per page."""
    return "<style>" + _ROOT + _BG + _CSS_BODY + "</style>"


# Backwards-compatible alias.
def global_css() -> str:
    return app_css()


def section(title: str) -> str:
    """A small uppercase section heading with an accent chip."""
    return f"<div class='kp-section'>{title}</div>"


def header_html(tagline: str = TAGLINE) -> str:
    """A navy hero banner with the dark-mode logo (light wordmark on navy)."""
    uri = logo_data_uri("dark", max_h=120)
    img = f"<img src='{uri}' style='height:58px'/>" if uri \
        else f"<h2 style='color:#fff;margin:0'>{NAME}</h2>"
    tag = (f"<div style='color:#cdddf7;font-size:.92rem;font-weight:500;"
           f"margin-left:auto;text-align:right;max-width:46%'>{tagline}</div>"
           if tagline else "")
    return (f"<div style='display:flex;align-items:center;gap:20px;"
            f"background:linear-gradient(120deg,{NAVY},#0b2a5e);border-radius:16px;"
            f"padding:16px 24px;margin-bottom:14px;"
            f"box-shadow:0 10px 30px rgba(0,0,0,.3)'>{img}{tag}</div>")
