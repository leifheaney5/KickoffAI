---
name: generate-report
description: Generate the Kickoff Pulse post-match coach report (polished PDF + plain-text + CSV exports + momentum graph) from the current match data into exports/. Use whenever the user asks to create, generate, build, export, or refresh a match/post-match/coach report.
---

# Generate the post-match report

Produces the coach-facing report bundle from the live match log
(`match_data.json`) and the saved match state (`control.json`): a polished PDF,
a plain-text version, CSV exports, and a momentum graph.

## Run it

From the repo root (`/Users/leifheaney/KickoffAI`):

```bash
.venv/bin/python report.py
```

This reads the current `match_data.json` + `control.json` (match name, clock,
summary, lineups), auto-detects team crests, writes the bundle into `exports/`,
and prints every output path. Files are named by teams + match date, e.g.
`Hub_City_FC_vs_Ristozi_FC_2026-06-24.pdf`. Then surface the PDF path to the
user and offer to open it:

```bash
open "$(ls -t exports/*.pdf | head -1)"
```

## What's in the report

Score · Possession & efficiency · **Match momentum graph** · Team stats ·
**By half** (grouped Home/Away per half, in team colours) · summary · notes.
Header/footer carry the contact email and page numbers. (Key Moments,
Substitutions, and the Visual Timeline were intentionally removed.)

## Inputs & options

- **Team crests**: `branding/teams/home.*` and `away.*` render in the scoreline
  band (PNG with transparency is best). Absent crests fall back gracefully.
- **Output directory**: `exports/` by default; override with
  `KICKOFF_REPORTS_DIR`.
- **Custom data/name/clock**: call `report.generate(...)` directly instead, e.g.
  `report.generate(events=..., match_name="A vs B", clock="90:00", out_dir="exports")`.
- **CV / vision** stats are intentionally not embedded in this report.

## Requirements & checks

- Needs `matplotlib` and `fpdf` in `.venv` (already installed). If `report.py`
  errors on imports, install with `.venv/bin/pip install -r requirements.txt`.
- If `exports/` fills with old bundles, they are git-ignored and safe to prune.
- After generating, if the user wants it committed, follow the repo's
  changelog/version rule (update `CHANGELOG.md` + roll the version).
