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
    # Wireframe design tokens
    "--c-bg1:#080b16;--c-bg2:#0b1126;"
    "--c-home:#1E7BFF;--c-home2:#4DA3FF;--c-signal:#4DA3FF;"
    "--c-away:#DC2626;--c-live:#FF3D6E;--c-cyan:#2BE7FF;"
    "--c-text:#EAF1FF;--c-muted:#9FB6DD;--c-subtle:#7E95BF;"
    "--panel:rgba(255,255,255,.055);--panel-2:rgba(255,255,255,.03);"
    "--border:rgba(255,255,255,.08);--border-2:rgba(255,255,255,.12);"
    "--radius:12px;--blur:12px;"
    "--shadow:0 10px 30px rgba(0,0,0,.35);"
    f"--font-disp:{FONT_DISPLAY};--font-body:{FONT_SANS};--font-mono:{FONT_MONO};"
    "--gap:16px;--pad:20px;--rowgap:10px;"
    # Legacy aliases — keep existing code working
    f"--fd:{FONT_DISPLAY};--fm:{FONT_MONO};"
    "--home:#1E7BFF;--away:#DC2626;"
    "--accent:#2BE7FF;--live:#FF3D6E;"
    "--txt:#EAF1FF;--muted:#9FB6DD;--muted2:#7E95BF;"
    "--glass:rgba(255,255,255,.055);--glass-2:rgba(255,255,255,.055);"
    "--glass-bd:rgba(255,255,255,.08);"
    "}"
)

# Background: stadium-light glows over a deep navy→blue gradient — simple,
# clean depth, no pitch lines.
_BG = (
    ".stApp{background:"
    "radial-gradient(900px 520px at 82% -8%, rgba(43,231,255,.16) 0%, transparent 60%),"
    "radial-gradient(800px 500px at 12% 8%, rgba(30,123,255,.20) 0%, transparent 55%),"
    "linear-gradient(165deg,#04102a 0%,#071f4d 48%,#0b2f74 100%) fixed;"
    "background-attachment:fixed;}"
)

_CSS_BODY = """
  @import url('https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=Sora:wght@400;500;600;700;800&family=Spline+Sans+Mono:wght@400;500;600&display=swap');

  html, body, [class*="css"], .stMarkdown, .stApp { font-family: var(--font-body); }
  .mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }

  [data-testid="stHeader"] { background: transparent; }
  [data-testid="stSidebar"] {
    background: rgba(8,11,22,.72); backdrop-filter: blur(14px);
    border-right: 1px solid var(--border);
  }
  .block-container { padding-top: 1.4rem; max-width: 1100px; margin: 0 auto; }

  .stApp { animation: kpAppIn .7s cubic-bezier(.22,.61,.36,1) both; }
  @keyframes kpAppIn { from{opacity:0;transform:translateY(10px) scale(.995);} to{opacity:1;transform:none;} }
  @keyframes kpFade { from{opacity:0;transform:translateY(8px);} to{opacity:1;transform:none;} }
  .kp-reveal { animation: kpFade .6s cubic-bezier(.22,.61,.36,1) both; }

  /* ---- Typography ---- */
  h1,h2,h3,h4,h5 { color:#fff !important; font-family:var(--font-disp) !important; font-weight:700; letter-spacing:.01em; }
  .stApp, .stMarkdown, .stApp p, .stApp label, .stApp li, .stApp span { color: var(--c-text); }
  [data-testid="stCaptionContainer"], .stCaption, .stCaption p { color: var(--c-muted) !important; }
  a { color: var(--c-cyan) !important; }

  /* ---- Panels ---- */
  .panel {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: var(--radius); backdrop-filter: blur(var(--blur));
    box-shadow: var(--shadow); padding: var(--pad);
  }
  .kp-card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: var(--radius); padding: var(--pad); box-shadow: var(--shadow);
    -webkit-backdrop-filter: blur(var(--blur)); backdrop-filter: blur(var(--blur));
    transition: border-color .18s ease;
  }
  .kp-card:hover { border-color: var(--border-2); }
  .card-title { font-family:var(--font-disp); font-weight:700; font-size:1.05rem; margin-bottom:10px; color:#fff; }
  .row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--border); font-size:.95rem; }
  .row:last-child { border-bottom:none; }
  .row .v { font-weight:700; font-family:var(--font-mono); }

  /* ---- Section labels ---- */
  .section-label { display:flex; align-items:flex-end; justify-content:space-between; gap:12px; margin-bottom:14px; }
  .section-label-l { border-left:3px solid var(--c-home); padding-left:11px; }
  .section-kicker { display:block; font-family:var(--font-mono); font-size:10px; letter-spacing:.18em; color:var(--c-subtle); text-transform:uppercase; }
  .section-title { font-family:var(--font-disp); font-weight:600; font-size:18px; color:var(--c-text); letter-spacing:.01em; white-space:nowrap; }

  /* ---- Status chips ---- */
  .kp-status { display:flex; gap:8px; flex-wrap:wrap; align-items:center; justify-content:center; }
  .kp-chip {
    display:inline-flex; align-items:center; gap:7px;
    background:rgba(255,255,255,.05); border:1px solid var(--border);
    border-radius:999px; padding:6px 14px; font-size:12px; color:var(--c-muted);
  }
  .kp-chip .l { font-family:var(--font-disp); font-size:.66rem; letter-spacing:.14em; text-transform:uppercase; color:var(--c-muted); font-weight:600; }
  .kp-chip .v { font-weight:700; color:var(--c-text); font-family:var(--font-mono); font-size:12px; }
  .kp-chip.heard { flex:1; min-width:180px; }
  .kp-heard { color:var(--c-muted); font-style:italic; font-size:.86rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .dot { width:9px; height:9px; border-radius:50%; display:inline-block; flex:none; }
  .dot.rec { background:var(--c-live); animation:recpulse 1.4s infinite; }
  .dot.paused { background:#f5a623; }
  .dot.off { background:transparent; border:2px solid #5b6e92; }
  @keyframes recpulse { 0%{box-shadow:0 0 0 0 rgba(255,61,110,.6);} 70%{box-shadow:0 0 0 10px rgba(255,61,110,0);} 100%{box-shadow:0 0 0 0 rgba(255,61,110,0);} }

  /* ---- Scoreboard ---- */
  .scoreboard { display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:24px; padding:calc(var(--pad) + 4px) var(--pad); }
  .sb-side { display:flex; flex-direction:column; align-items:center; gap:6px; }
  .sb-team { font-family:var(--font-disp); font-weight:600; font-size:16px; letter-spacing:.03em; color:var(--c-muted); }
  .sb-home .sb-team { color:var(--c-home2); }
  .sb-away .sb-team { color:#FF6B6B; }
  .sb-score { font-family:var(--font-mono); font-size:68px; font-weight:600; line-height:1; color:var(--c-text); }
  .sb-center { display:flex; flex-direction:column; align-items:center; gap:8px; min-width:200px; }
  .sb-half { font-family:var(--font-mono); font-size:11px; letter-spacing:.22em; color:var(--c-subtle); text-transform:uppercase; }
  .sb-clock { font-family:var(--font-mono); font-size:46px; font-weight:500; color:var(--c-text); text-shadow:0 0 24px rgba(43,231,255,.25); }
  .sb-clock .added { color:var(--c-cyan); font-size:1.3rem; font-weight:500; }

  /* ---- Team comparison bars ---- */
  .cmp-legend { display:flex; justify-content:space-between; font-size:11px; color:var(--c-muted); margin-bottom:12px; font-family:var(--font-disp); }
  .cmp-legend span { display:flex; align-items:center; gap:6px; }
  .cmp-dot { width:9px; height:9px; border-radius:50%; display:inline-block; }
  .cmp-dot.home { background:var(--c-home); }
  .cmp-dot.away { background:var(--c-away); }
  .cmp-rows { display:flex; flex-direction:column; gap:var(--rowgap); }
  .cmp-row { display:grid; grid-template-columns:46px 1fr 46px; align-items:center; gap:10px; }
  .cmp-val { font-size:14px; font-weight:600; font-family:var(--font-mono); }
  .cmp-val.home { text-align:right; color:var(--c-home2); }
  .cmp-val.away { text-align:left; color:#FF6B6B; }
  .cmp-bars { display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:8px; }
  .cmp-left, .cmp-right { height:9px; background:rgba(255,255,255,.05); border-radius:99px; overflow:hidden; display:flex; }
  .cmp-left { justify-content:flex-end; }
  .cmp-fill { height:100%; border-radius:99px; transition:width .4s ease; }
  .cmp-fill.home { background:linear-gradient(90deg,rgba(30,123,255,.4),var(--c-home)); }
  .cmp-fill.away { background:linear-gradient(90deg,var(--c-away),rgba(220,38,38,.4)); }
  .cmp-mid { font-family:var(--font-mono); font-size:10px; letter-spacing:.04em; color:var(--c-subtle); text-transform:uppercase; min-width:72px; text-align:center; }

  /* ---- Team chip ---- */
  .team-chip { display:inline-flex; align-items:center; font-family:var(--font-disp); font-weight:700; font-size:10px; letter-spacing:.06em; padding:3px 7px; border-radius:6px; border:1px solid; flex:none; }

  /* ---- Live feed ---- */
  .feed-list { display:flex; flex-direction:column; gap:8px; }
  .feed-item { display:flex; gap:12px; padding:10px; border-radius:10px; background:var(--panel-2); border:1px solid var(--border); transition:all .15s ease; }
  .feed-item:hover { background:rgba(255,255,255,.06); border-color:var(--border-2); }
  .ev-badge { border-radius:50%; display:grid; place-items:center; flex:none; }
  .feed-body { min-width:0; flex:1; }
  .feed-meta { display:flex; align-items:center; gap:8px; margin-bottom:3px; flex-wrap:wrap; }
  .feed-type { font-family:var(--font-disp); font-size:11px; font-weight:600; color:var(--c-muted); text-transform:uppercase; letter-spacing:.04em; }
  .feed-time { font-size:11px; color:var(--c-subtle); margin-left:auto; font-family:var(--font-mono); }
  .feed-desc { font-size:13px; color:var(--c-text); line-height:1.45; }
  .feed-desc b { color:var(--c-home2); font-weight:600; }

  /* ---- Buttons ---- */
  .stButton > button, .stDownloadButton > button {
    font-family: var(--font-disp) !important; font-weight:600 !important; font-size:12.5px !important;
    letter-spacing:.04em !important; text-transform:uppercase !important;
    border-radius:9px !important; border:1px solid var(--border) !important;
    background:rgba(255,255,255,.04) !important; color:var(--c-muted) !important;
    transition:all .18s !important;
  }
  .stButton > button:hover, .stDownloadButton > button:hover {
    color:var(--c-text) !important; border-color:var(--border-2) !important;
    background:rgba(255,255,255,.07) !important; transform:translateY(-1px);
  }
  .stButton > button[kind="primary"] {
    color:#fff !important; border-color:transparent !important;
    background:linear-gradient(135deg,var(--c-home),#1462d6) !important;
    box-shadow:0 6px 16px rgba(30,123,255,.3) !important;
  }
  .stButton > button[kind="primary"]:hover { filter:brightness(1.08); color:#fff !important; }

  /* ---- Inputs ---- */
  .stTextArea textarea { background:rgba(255,255,255,.05) !important; color:var(--c-text) !important;
    border:1px solid var(--border-2) !important; border-radius:10px !important; }
  .stTextArea textarea::placeholder { color:var(--c-subtle) !important; }
  div[data-baseweb="select"] > div { background:rgba(255,255,255,.05) !important;
    border-color:var(--border-2) !important; border-radius:8px !important; color:var(--c-text) !important; }
  .stTextInput input { background:rgba(255,255,255,.05) !important; color:var(--c-text) !important;
    border:1px solid var(--border-2) !important; border-radius:8px !important; }

  /* ---- Expanders ---- */
  [data-testid="stExpander"] { background:var(--panel) !important; border:1px solid var(--border) !important;
    border-radius:var(--radius) !important; -webkit-backdrop-filter:blur(var(--blur)); backdrop-filter:blur(var(--blur)); }
  [data-testid="stExpander"] summary { color:var(--c-text) !important; font-family:var(--font-disp) !important; font-weight:600 !important; }
  [data-testid="stExpander"] summary:hover { color:var(--c-cyan) !important; }

  /* ---- Page headers (timeline / insights) ---- */
  .page-head { display:flex; align-items:center; justify-content:space-between; padding-bottom:4px; margin-bottom:16px; }
  .page-kicker { display:block; font-family:var(--font-mono); font-size:11px; letter-spacing:.2em; color:var(--c-subtle); text-transform:uppercase; }
  .page-title { display:block; font-family:var(--font-disp); font-weight:700; font-size:30px; letter-spacing:.01em; background:linear-gradient(90deg,#fff,var(--c-home2)); -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }

  /* ---- Popover (match title) ---- */
  div[data-testid="stPopover"] { display:flex; justify-content:center; }
  div[data-testid="stPopover"] > div button { border:none !important; background:transparent !important; padding:0 !important; box-shadow:none !important; }
  div[data-testid="stPopover"] > div button p { font-family:var(--font-disp) !important; font-size:1.55rem !important; font-weight:700 !important; color:#fff !important; letter-spacing:.01em; }
  div[data-testid="stPopover"] > div button:hover p { color:var(--c-cyan) !important; }

  /* ---- Tabs ---- */
  .stTabs [data-baseweb="tab-list"] { gap:6px; border-bottom:1px solid var(--border); }
  .stTabs [data-baseweb="tab"] { color:var(--c-muted); font-weight:700; }
  .stTabs [aria-selected="true"] { color:#fff !important; }
  .stTabs [data-baseweb="tab-highlight"] { background:var(--c-home) !important; }

  /* ---- Detail rows (timeline expand) ---- */
  .det { display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid var(--border); font-size:.95rem; }
  .det:last-child { border-bottom:none; }
  .det .k { color:var(--c-muted); }
  .legend { display:flex; flex-wrap:wrap; gap:14px; margin:4px 0 8px; }
  .legend .item { display:flex; align-items:center; gap:6px; font-size:.85rem; color:var(--c-muted); }

  /* ---- AI chat (insights) ---- */
  .kp-ana { display:flex; flex-direction:column; }
  .kp-msg { border-radius:14px; padding:12px 16px; margin:6px 0; max-width:86%; line-height:1.5; animation:kpFade .3s ease both; }
  .kp-msg.user { align-self:flex-end; color:#fff; background:linear-gradient(135deg,var(--c-home),#1462d6); border-bottom-right-radius:4px; }
  .kp-msg.ai { align-self:flex-start; color:var(--c-text); background:var(--panel-2); border:1px solid var(--border); border-bottom-left-radius:4px; }
  .kp-msg .who { display:block; font-family:var(--font-mono); font-size:.64rem; letter-spacing:.16em; color:var(--c-cyan); margin-bottom:5px; text-transform:uppercase; }

  /* ---- Streamlit chrome cleanup ---- */
  [data-testid="stDecoration"] { display:none !important; }
  footer { visibility:hidden; height:0; }
  [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] {
    background:transparent !important; border:none !important; box-shadow:none !important;
    -webkit-backdrop-filter:none !important; backdrop-filter:none !important;
  }
  [data-testid="stSidebarCollapsedControl"] button { color:#cfe0ff !important; }
  [data-testid="stSidebarNav"] a span, [data-testid="stSidebarNav"] a { color:var(--c-text) !important; }
  [data-testid="stToolbar"] { background:transparent !important; }
"""


def app_css() -> str:
    """The full Kickoff Pulse design system — inject once per page."""
    return "<style>" + _ROOT + _BG + _CSS_BODY + "</style>"


# Backwards-compatible alias.
def global_css() -> str:
    return app_css()


def section(title: str, kicker: str = "") -> str:
    """Section label with mono kicker + display title and accent left border."""
    k = kicker or title.upper()
    return (
        f"<div class='section-label'>"
        f"<div class='section-label-l'>"
        f"<span class='section-kicker'>{k}</span>"
        f"<h3 class='section-title'>{title}</h3>"
        f"</div>"
        f"</div>"
    )


def page_header(kicker: str, title: str) -> str:
    """Page header with mono kicker and gradient display title (timeline/insights)."""
    return (
        f"<div class='page-head'>"
        f"<div>"
        f"<span class='page-kicker'>{kicker}</span>"
        f"<span class='page-title'>{title}</span>"
        f"</div>"
        f"</div>"
    )


def header_html(tagline: str = TAGLINE) -> str:
    """Legacy nav banner — kept for backward compat, prefer page_header() on new pages."""
    uri = logo_data_uri("dark", max_h=120)
    img = f"<img src='{uri}' style='height:48px'/>" if uri \
        else f"<h2 style='color:#fff;margin:0'>{NAME}</h2>"
    tag = (f"<div style='color:#9fb6dd;font-size:.88rem;font-weight:500;"
           f"margin-left:auto;text-align:right;max-width:46%'>{tagline}</div>"
           if tagline else "")
    return (f"<div style='display:flex;align-items:center;gap:20px;"
            f"background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);"
            f"border-radius:12px;padding:14px 20px;margin-bottom:14px;"
            f"backdrop-filter:blur(12px);box-shadow:0 10px 30px rgba(0,0,0,.3)'>{img}{tag}</div>")
