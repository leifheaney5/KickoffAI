# Exports

Generated report bundles and artifacts land here — the default output directory
for `report.generate` (`REPORTS_DIR`, override with `KICKOFF_REPORTS_DIR`).

Each match export is a timestamped set:

- `match_report_<ts>.pdf` / `.txt` — the coach report
- `match_momentum_<ts>.png` — momentum graph
- `match_timeline_<ts>.png` — visual timeline
- `match_events_<ts>.csv`, `match_team_stats_<ts>.csv`, `match_player_stats_<ts>.csv`
- `match_data_<ts>.json` — archived raw event log (when archiving is enabled)

The contents are regenerable, so they are git-ignored; this directory itself is
kept in the repo via `.gitkeep`.
