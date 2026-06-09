#!/usr/bin/env python3
"""
Kickoff Pulse — report generator.

Compiles the logged match data into:
  - an email-friendly plain-text report (reports/match_report_<ts>.txt)
  - a clean PDF report                  (reports/match_report_<ts>.pdf)
and archives a copy of the raw data     (reports/match_data_<ts>.json)

Usable from the command line:
    python report.py
or programmatically from the dashboard:
    import report; paths = report.generate(summary="...", clock="73:12")
"""

import json
import os
import shutil
from datetime import datetime

import stats as S
import timeline_image as TL

REPORTS_DIR = os.environ.get("KICKOFF_REPORTS_DIR", "reports")

HOME_RGB = (30, 123, 255)   # Pulse Blue (brand)
AWAY_RGB = (220, 38, 38)    # red
NAVY_RGB = (7, 26, 61)      # Primary Navy (brand)
INK = (17, 24, 39)          # Dark Text (brand)
MUTED = (107, 114, 128)
LINE = (222, 226, 230)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _event_time(e: dict) -> str:
    """Prefer the match clock if it was stamped, else the wall time."""
    if e.get("match_time"):
        return str(e["match_time"])
    ts = e.get("timestamp", "")
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M:%S")
    except ValueError:
        return ts


def _event_summary(e: dict) -> str:
    parts = [p for p in [
        e.get("action"),
        e.get("result"),
        (f"by {e['player']}" if e.get("player") else None),
        (f"@ {e['location']}" if e.get("location") else None),
    ] if p]
    return " / ".join(parts) if parts else f'"{e.get("raw_text", "")}"'


def _collect(events):
    home = S.team_stats(events, "Home")
    away = S.team_stats(events, "Away")
    return {
        "home": home,
        "away": away,
        "players": S.player_stats(events),
        "subs": [e for e in events if e.get("action") == "substitution"],
    }


# --------------------------------------------------------------------------- #
# Plain-text report
# --------------------------------------------------------------------------- #
def build_text(events, data, summary, clock, match_name="") -> str:
    home, away = data["home"], data["away"]
    L = []
    w = 56

    def rule(ch="="):
        L.append(ch * w)

    rule()
    L.append("KICKOFF PULSE  -  MATCH REPORT".center(w))
    rule()
    if match_name:
        L.append(match_name.center(w))
        L.append("")
    L.append(f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if clock:
        L.append(f"Match clock: {clock}")
    L.append(f"Events    : {len(events)}")
    L.append("")
    L.append(f"FINAL SCORE   HOME {home['Goals']}  -  {away['Goals']} AWAY")
    L.append("")
    rule("-")
    L.append(f"{'HOME':>10}   {'STAT':^18}   {'AWAY':<10}")
    rule("-")
    for k in S.STAT_KEYS:
        L.append(f"{home[k]:>10}   {k:^18}   {away[k]:<10}")
    L.append("")

    # Player stats
    players = data["players"]
    if players:
        rule("-")
        L.append("PLAYER STATS")
        rule("-")
        header = f"{'Player':<14}{'Team':<6}{'G':>3}{'Sh':>4}{'Tk':>4}{'Fl':>4}{'Y':>3}{'R':>3}"
        L.append(header)
        ordered = sorted(players.items(),
                         key=lambda kv: (kv[1]["Goals"], kv[1]["Events"]),
                         reverse=True)
        for name, p in ordered:
            L.append(
                f"{name[:13]:<14}{(p['Team'] or '-')[:5]:<6}"
                f"{p['Goals']:>3}{p['Shots']:>4}{p['Tackles']:>4}"
                f"{p['Fouls']:>4}{p['Yellow Cards']:>3}{p['Red Cards']:>3}"
            )
        L.append("")

    # Substitutions
    if data["subs"]:
        rule("-")
        L.append("SUBSTITUTIONS")
        rule("-")
        for e in data["subs"]:
            who = e.get("player") or "unknown"
            L.append(f"  {_event_time(e):>8}  {e.get('team') or '-':<5}  {who}")
        L.append("")

    # Post-match summary
    if summary:
        rule("-")
        L.append("POST-MATCH SUMMARY")
        rule("-")
        for line in summary.splitlines() or [summary]:
            L.append(line)
        L.append("")

    # Full timeline
    rule("-")
    L.append("EVENT TIMELINE")
    rule("-")
    for e in events:
        team = (e.get("team") or "-")
        L.append(f"  {_event_time(e):>8}  {team:<5}  {_event_summary(e)}")
    rule()
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# PDF report
# --------------------------------------------------------------------------- #
def build_pdf(events, data, summary, clock, path, timeline_png=None,
              match_name=""):
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    home, away = data["home"], data["away"]

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    epw = pdf.epw  # effective page width

    def text(txt, size=11, style="", color=INK, h=6, align="L"):
        pdf.set_font("Helvetica", style, size)
        pdf.set_text_color(*color)
        pdf.cell(0, h, txt, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align=align)

    # Header — brand logo (falls back to a wordmark if the asset is missing)
    import brand
    logo = brand.logo_pil_white()
    if logo is not None:
        try:
            y0 = pdf.get_y()
            lw = 58
            pdf.image(logo, x=pdf.l_margin, y=y0, w=lw)
            pdf.set_y(y0 + lw * logo.height / logo.width + 3)
        except Exception:
            text("KICKOFF PULSE", 22, "B", NAVY_RGB, h=10)
    else:
        text("KICKOFF PULSE", 22, "B", NAVY_RGB, h=10)
    text(match_name or "Match Report", 13, "", MUTED, h=7)
    meta = f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    if clock:
        meta += f"   |   Match clock {clock}"
    meta += f"   |   {len(events)} events"
    text(meta, 9, "", MUTED, h=6)
    pdf.ln(2)

    # Scoreline band
    pdf.set_fill_color(245, 247, 250)
    pdf.set_draw_color(*LINE)
    y0 = pdf.get_y()
    pdf.rect(pdf.l_margin, y0, epw, 22, style="DF")
    pdf.set_xy(pdf.l_margin, y0 + 3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*HOME_RGB)
    pdf.cell(epw / 2, 6, "HOME", align="C")
    pdf.set_text_color(*AWAY_RGB)
    pdf.cell(epw / 2, 6, "AWAY", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*HOME_RGB)
    pdf.cell(epw / 2, 11, str(home["Goals"]), align="C")
    pdf.set_text_color(*AWAY_RGB)
    pdf.cell(epw / 2, 11, str(away["Goals"]),
             new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.ln(6)

    # Team comparison table
    def stat_row(label, hv, av, header=False):
        pdf.set_x(pdf.l_margin)
        style = "B" if header else ""
        pdf.set_font("Helvetica", style, 10)
        pdf.set_text_color(*(HOME_RGB if not header else INK))
        pdf.cell(epw * 0.25, 7, str(hv), border="B", align="C")
        pdf.set_text_color(*INK)
        pdf.set_font("Helvetica", "B" if header else "", 10)
        pdf.cell(epw * 0.50, 7, label, border="B", align="C")
        pdf.set_text_color(*(AWAY_RGB if not header else INK))
        pdf.cell(epw * 0.25, 7, str(av), border="B", align="C",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    text("Team Stats", 13, "B", INK, h=8)
    stat_row("HOME", "", "AWAY", header=True)
    for k in S.STAT_KEYS:
        stat_row(k, str(home[k]), str(away[k]))
    pdf.ln(4)

    # Player stats table
    players = data["players"]
    if players:
        text("Player Stats", 13, "B", INK, h=8)
        cols = [("Player", 0.28), ("Team", 0.13), ("G", 0.10), ("Sh", 0.10),
                ("Tk", 0.10), ("Fl", 0.10), ("Y", 0.10), ("R", 0.09)]
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*INK)
        for name, frac in cols:
            pdf.cell(epw * frac, 6, name, border="B", align="C")
        pdf.ln(6)
        ordered = sorted(players.items(),
                         key=lambda kv: (kv[1]["Goals"], kv[1]["Events"]),
                         reverse=True)
        pdf.set_font("Helvetica", "", 9)
        for nm, p in ordered:
            vals = [nm[:16], p["Team"] or "-", p["Goals"], p["Shots"],
                    p["Tackles"], p["Fouls"], p["Yellow Cards"], p["Red Cards"]]
            pdf.set_x(pdf.l_margin)
            for (name, frac), v in zip(cols, vals):
                pdf.cell(epw * frac, 6, str(v), border="B",
                         align="L" if name == "Player" else "C")
            pdf.ln(6)
        pdf.ln(4)

    # Substitutions
    if data["subs"]:
        text("Substitutions", 13, "B", INK, h=8)
        for e in data["subs"]:
            who = e.get("player") or "unknown"
            text(f"  {_event_time(e)}   {e.get('team') or '-'}   {who}",
                 9, "", INK, h=5)
        pdf.ln(2)

    # Summary
    if summary:
        text("Post-Match Summary", 13, "B", INK, h=8)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 6, summary)
        pdf.ln(2)

    # Timeline
    text("Event Timeline", 13, "B", INK, h=8)
    pdf.set_font("Helvetica", "", 9)
    for e in events:
        pdf.set_x(pdf.l_margin)
        pdf.set_text_color(*MUTED)
        pdf.cell(epw * 0.14, 5, _event_time(e), align="L")
        team = e.get("team")
        pdf.set_text_color(*(HOME_RGB if team == "Home"
                             else AWAY_RGB if team == "Away" else MUTED))
        pdf.cell(epw * 0.12, 5, team or "-", align="L")
        pdf.set_text_color(*INK)
        pdf.multi_cell(epw * 0.74, 5, _event_summary(e),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Visual timeline image on its own page, scaled to fit.
    if timeline_png and os.path.exists(timeline_png):
        from PIL import Image
        pdf.add_page()
        text("Visual Timeline", 13, "B", INK, h=8)
        with Image.open(timeline_png) as im:
            iw, ih = im.size
        aspect = iw / ih
        max_w, max_h = epw, pdf.h - pdf.get_y() - pdf.b_margin
        w = max_w
        h = w / aspect
        if h > max_h:
            h = max_h
            w = h * aspect
        pdf.image(timeline_png, x=pdf.l_margin + (epw - w) / 2,
                  y=pdf.get_y(), w=w, h=h)

    pdf.output(path)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def generate(events=None, summary="", clock="", out_dir=None,
             data_file=None, archive=True, match_name="") -> dict:
    """Generate txt + pdf reports (and archive data). Returns the paths."""
    out_dir = out_dir or REPORTS_DIR
    os.makedirs(out_dir, exist_ok=True)
    data_file = data_file or S.DATA_FILE
    if events is None:
        events = S.load_events(data_file)

    data = _collect(events)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    txt_path = os.path.join(out_dir, f"match_report_{ts}.txt")
    pdf_path = os.path.join(out_dir, f"match_report_{ts}.pdf")
    png_path = os.path.join(out_dir, f"match_timeline_{ts}.png")

    # Render the visual timeline image (embedded in the PDF + saved alongside).
    score = (data["home"]["Goals"], data["away"]["Goals"])
    try:
        TL.render(events, score=score, clock=clock, path=png_path)
    except Exception:
        png_path = None

    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(build_text(events, data, summary, clock, match_name))
    build_pdf(events, data, summary, clock, pdf_path, timeline_png=png_path,
              match_name=match_name)

    result = {"txt": txt_path, "pdf": pdf_path, "events": len(events)}
    if png_path:
        result["image"] = png_path
    if archive and os.path.exists(data_file):
        archive_path = os.path.join(out_dir, f"match_data_{ts}.json")
        shutil.copyfile(data_file, archive_path)
        result["data"] = archive_path
    return result


if __name__ == "__main__":
    import control
    state = control.load_control()
    main_clk, added, half = control.clock_label(state["timer"])
    clock = f"{main_clk}{(' ' + added) if added else ''} ({half})"
    paths = generate(summary=state.get("summary", ""), clock=clock,
                     match_name=state.get("match_name", ""))
    print("Report written:")
    for k, v in paths.items():
        print(f"  {k}: {v}")
