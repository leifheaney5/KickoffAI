#!/usr/bin/env python3
"""
Kickoff Pulse — seed demo matches into the library.

Generates a handful of realistic matches (events, scorelines, competitions) and
archives each through the normal finalize pipeline, so the Match Library, Season
page, and Library Analyst all have data to explore.

Usage (point at your DB first; Postgres recommended so search/analyst work):
    export KICKOFF_DB_URL="postgresql+psycopg://kickoff:kickoff@localhost:5432/kickoff"
    python seed_test_data.py

Re-running creates additional (suffixed) matches; it does not de-duplicate.
"""

import json
import os
import random
import tempfile

# Library media must land in the repo's library/, regardless of the temp CWD we
# use below to isolate report archiving. Set before importing library/finalize.
_REPO = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("KICKOFF_LIBRARY_ROOT", os.path.join(_REPO, "library"))

import finalize  # noqa: E402

# (home, away, home_goals, away_goals, competition, date, summary)
MATCHES = [
    ("Hub City FC", "Riverside United", 3, 1, "Spring League — Round 9",
     "2026-05-03", "Comfortable home win; clinical in front of goal."),
    ("Oakwood Athletic", "Hub City FC", 2, 2, "Spring League — Round 10",
     "2026-05-10", "Hard-fought away draw, conceded a late equaliser."),
    ("Hub City FC", "Metro Rovers", 0, 1, "Spring League — Round 11",
     "2026-05-17", "Frustrating loss — dominated the ball but no end product."),
    ("Riverside United", "Oakwood Athletic", 1, 4, "Spring League — Round 11",
     "2026-05-17", "Oakwood ran riot in the second half."),
    ("Metro Rovers", "Riverside United", 2, 0, "County Cup — Quarter-final",
     "2026-05-24", "Controlled cup tie, two first-half goals enough."),
]


def _mmss(minute: float) -> str:
    s = int(minute * 60)
    return f"{s // 60:02d}:{s % 60:02d}"


def generate_events(hg: int, ag: int, rng: random.Random) -> list:
    evs = []

    def add(minute, team, action, result=None, player=None, location=None):
        evs.append({
            "timestamp": "2026-01-01T00:00:00+00:00", "match_time": _mmss(minute),
            "team": team, "player": player, "action": action, "result": result,
            "location": location, "status": "approved",
            "raw_text": f"{team} {action} {result or ''}".strip()})

    for team, n in (("Home", hg), ("Away", ag)):
        for _ in range(n):
            add(rng.uniform(2, 89), team, "goal", "scored",
                f"#{rng.choice([7, 9, 10, 11])}", "box")
    for team in ("Home", "Away"):
        for _ in range(rng.randint(6, 12)):
            add(rng.uniform(1, 90), team, "shot",
                rng.choice(["on target", "missed", "blocked"]),
                f"#{rng.randint(2, 11)}")
        for _ in range(rng.randint(15, 28)):
            add(rng.uniform(1, 90), team, "pass", "complete",
                f"#{rng.randint(2, 11)}", "midfield")
        for _ in range(rng.randint(4, 9)):
            add(rng.uniform(1, 90), team, "tackle", "won", f"#{rng.randint(2, 11)}")
        for _ in range(rng.randint(3, 8)):
            add(rng.uniform(1, 90), team, "foul", None, f"#{rng.randint(2, 11)}")
        for _ in range(rng.randint(2, 6)):
            add(rng.uniform(1, 90), team, "corner")
        for _ in range(rng.randint(1, 5)):
            add(rng.uniform(1, 90), team, "save", "saved", "#1")
    for _ in range(rng.randint(1, 3)):
        add(rng.uniform(20, 90), rng.choice(["Home", "Away"]), "card", "yellow",
            f"#{rng.randint(2, 11)}")

    evs.sort(key=lambda e: e["match_time"])
    return evs


def seed():
    rng = random.Random(42)
    created = []
    start_cwd = os.getcwd()
    for home, away, hg, ag, comp, date_, summary in MATCHES:
        events = generate_events(hg, ag, rng)
        state = {
            "match_name": "", "competition": comp, "match_date": date_,
            "summary": summary,
            "teams": {"home": {"name": home}, "away": {"name": away}},
            "lineups": {"Home": {"formation": "4-3-3", "players": []},
                        "Away": {"formation": "4-4-2", "players": []}},
        }
        # Isolate report archiving in a temp CWD, but write this match's
        # match_data.json there so the raw-data artifact is captured too.
        with tempfile.TemporaryDirectory(prefix="kp_seed_") as tmp:
            os.chdir(tmp)
            try:
                with open("match_data.json", "w") as fh:
                    json.dump(events, fh)
                slug = finalize.finalize_match(
                    events=events, state=state, notes=[],
                    clock="90:00 (2nd Half)")
                created.append((slug, f"{home} {hg}-{ag} {away}"))
            finally:
                os.chdir(start_cwd)
    return created


if __name__ == "__main__":
    rows = seed()
    print(f"Seeded {len(rows)} matches:")
    for slug, label in rows:
        print(f"  {label:42}  ->  {slug}")
