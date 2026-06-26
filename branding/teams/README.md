# Team crests

Drop a club crest here and the report embeds it in the scoreline band:

- `home.png` — the Home team crest (e.g. Hub City FC)
- `away.png` — the Away team crest (e.g. Ristozi FC)

PNG with transparency looks best. `.jpg`/`.jpeg`/`.webp` also work. Override the
folder with `KICKOFF_TEAM_LOGO_DIR`, or pass explicit paths to
`report.generate(home_logo=..., away_logo=...)`.
