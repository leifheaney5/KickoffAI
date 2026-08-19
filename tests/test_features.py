"""Tests for clips, player development and share packs.

The clip tests concentrate on alignment, because that is the part with a real
failure mode: mapping the match clock onto video time puts every second-half
event minutes early, and the whole feature is worthless if the cuts are wrong.
"""

from datetime import datetime, timedelta, timezone

import clips as CL
import player_pack as PP
import season


START = datetime(2026, 8, 19, 19, 0, 0, tzinfo=timezone.utc)


def ev(seconds_after_start, match_time, action="goal", team="Home",
       player="#9", result=None):
    e = {"timestamp": (START + timedelta(seconds=seconds_after_start)).isoformat(),
         "match_time": match_time, "action": action, "team": team,
         "player": player, "status": "approved"}
    if result:
        e["result"] = result
    return e


ANCHOR = CL.anchor_from_recording(START.timestamp())


# --------------------------------------------------------------------------- #
# Alignment
# --------------------------------------------------------------------------- #
def test_video_position_is_wall_clock_offset():
    assert CL.video_position(ev(90, "01:00"), ANCHOR) == 90


def test_alignment_survives_the_half_time_break():
    """The failure the match clock causes, asserted directly.

    Kickoff 5 min in, 15 min break. A second-half event at match 50:00 sits at
    video 70:00 — mapping match time onto video time would cut 20 minutes early.
    """
    second_half = ev((5 + 45 + 15 + 5) * 60, "50:00")

    pos = CL.video_position(second_half, ANCHOR)

    assert pos == 70 * 60
    assert pos != 50 * 60          # what naive match-clock mapping would give


def test_anchor_can_be_derived_from_a_moment_in_the_video():
    """Nobody knows when recording started; everyone can find the first goal."""
    goal = ev(12 * 60, "07:00")

    anchor = CL.anchor_from_event(goal, video_seconds=12 * 60)

    assert anchor["started_at"] == START.timestamp()
    assert CL.video_position(goal, anchor) == 12 * 60


def test_unparseable_timestamps_do_not_crash_the_plan():
    assert CL.video_position({"timestamp": "not-a-time"}, ANCHOR) is None
    assert CL.anchor_from_event({"timestamp": None}, 10) is None
    assert CL.plan_clips([{"timestamp": "junk", "action": "goal"}], ANCHOR) == []


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
def test_only_reviewable_moments_are_clipped():
    assert CL.is_clipworthy(ev(0, "01:00", "goal")) is True
    assert CL.is_clipworthy(ev(0, "01:00", "card", result="yellow")) is True
    assert CL.is_clipworthy(ev(0, "01:00", "shot", result="on target")) is True
    # A shot into row Z, a routine pass, and a denied event are not worth a clip.
    assert CL.is_clipworthy(ev(0, "01:00", "shot", result="missed")) is False
    assert CL.is_clipworthy(ev(0, "01:00", "pass")) is False
    denied = ev(0, "01:00", "goal")
    denied["status"] = "denied"
    assert CL.is_clipworthy(denied) is False


def test_goals_get_a_longer_window_than_cards():
    """Build-up matters for a goal; a card is the moment itself."""
    _, goal_pre, goal_post = CL.clip_window(ev(0, "01:00", "goal"))
    _, card_pre, card_post = CL.clip_window(ev(0, "01:00", "card",
                                               result="yellow"))

    assert goal_pre > card_pre and goal_post > card_post


def test_events_outside_the_video_are_flagged_not_cut():
    plan = CL.plan_clips([ev(10, "00:10"), ev(9999, "88:00")],
                         ANCHOR, duration=120)

    assert [c["ok"] for c in plan] == [True, False]
    assert "after the video" in plan[1]["why"]


def test_events_before_the_recording_are_flagged():
    """A recording started after kickoff must not produce negative cuts."""
    late = CL.anchor_from_recording(START.timestamp() + 600)

    plan = CL.plan_clips([ev(60, "01:00")], late, duration=3600)

    assert plan[0]["ok"] is False
    assert "before the video" in plan[0]["why"]
    assert plan[0]["start"] >= 0


def test_clip_start_never_goes_negative():
    plan = CL.plan_clips([ev(2, "00:02")], ANCHOR, duration=600)

    assert plan[0]["start"] == 0.0


def test_clip_names_identify_the_moment():
    plan = CL.plan_clips([ev(60, "12:30", "goal", "Home", "#9")], ANCHOR,
                         duration=600)

    name = plan[0]["name"]
    assert name.endswith(".mp4")
    assert "12-30" in name and "goal" in name and "home" in name and "9" in name


# --------------------------------------------------------------------------- #
# Player development
# --------------------------------------------------------------------------- #
def _rows():
    rows = []
    for i, day in enumerate(["2026-05-01", "2026-05-08", "2026-05-15"]):
        m = f"Match {i + 1}"
        rows += [{"player": "#9", "team": "Eagles", "action": "goal",
                  "match": m, "played_on": day}] * i
        rows.append({"player": "#9", "team": "Eagles", "action": "shot",
                     "result": "on target", "match": m, "played_on": day})
        rows.append({"player": "#4", "team": "Eagles", "action": "tackle",
                     "match": m, "played_on": day})
    # A player who appeared only once.
    rows.append({"player": "#7", "team": "Eagles", "action": "shot",
                 "result": "missed", "match": "Match 1",
                 "played_on": "2026-05-01"})
    return rows


def test_player_season_totals_and_appearances():
    people = season.player_season(_rows())
    nine = next(p for p in people if p["player"] == "#9")

    assert nine["appearances"] == 3
    assert nine["totals"]["Goals"] == 3        # 0 + 1 + 2 across three matches
    # Three goals each count as a shot on target, plus the one logged shot in
    # each of the three matches.
    assert nine["totals"]["Shots"] == 6
    assert nine["totals"]["On Target"] == 6
    assert [m["Goals"] for m in nine["matches"]] == [0, 1, 2]


def test_a_goal_also_counts_as_a_shot_on_target():
    people = season.player_season([
        {"player": "#9", "action": "goal", "match": "M", "played_on": "2026-05-01"}])

    totals = people[0]["totals"]
    assert (totals["Goals"], totals["Shots"], totals["On Target"]) == (1, 1, 1)


def test_denied_events_do_not_count(_=None):
    rows = [{"player": "#9", "action": "goal", "match": "M",
             "played_on": "2026-05-01", "status": "denied"}]

    assert season.player_season(rows) == []


def test_form_compares_a_player_to_their_own_baseline():
    people = season.player_season(_rows())
    nine = next(p for p in people if p["player"] == "#9")

    form = season.player_form(nine, "Goals", window=1)

    assert form["recent"] == 2.0        # most recent match
    assert form["baseline"] == 1.0      # season average
    assert form["trend"] == "up"


def test_form_is_flat_without_enough_history():
    empty = season.player_form({"matches": []}, "Goals")

    assert empty["trend"] == "flat"
    assert empty["matches"] == 0


def test_squad_involvement_surfaces_least_used_players_first():
    people = season.player_season(_rows())

    rows = season.squad_involvement(people, total_matches=3)

    assert rows[0]["player"] == "#7"     # one appearance of three
    assert rows[0]["share"] == 33


# --------------------------------------------------------------------------- #
# Share packs
# --------------------------------------------------------------------------- #
def test_a_pack_contains_only_the_named_player(tmp_path):
    events = [
        {"timestamp": START.isoformat(), "match_time": "05:00", "team": "Home",
         "action": "goal", "result": "scored", "player": "#9",
         "status": "approved"},
        {"timestamp": START.isoformat(), "match_time": "20:00", "team": "Home",
         "action": "tackle", "player": "#4", "status": "approved"},
    ]
    made = {"clips": [
        {"player": "#9", "path": str(tmp_path / "a.mp4"), "label": "GOAL",
         "match_time": "05:00"},
        {"player": "#4", "path": str(tmp_path / "b.mp4"), "label": "Tackle",
         "match_time": "20:00"},
    ]}
    (tmp_path / "a.mp4").write_bytes(b"clipA")
    (tmp_path / "b.mp4").write_bytes(b"clipB")

    pack = PP.build_pack("#9", events, clip_results=made,
                         match_name="Eagles vs Hawks", out_dir=str(tmp_path))

    import zipfile
    with zipfile.ZipFile(pack["path"]) as z:
        names = z.namelist()
        summary = z.read("summary.txt").decode()
    assert any("a.mp4" in n for n in names)
    assert not any("b.mp4" in n for n in names)   # the other player's clip
    assert "#4" not in summary                     # nor their name


def test_the_card_adapts_to_how_much_a_player_did():
    """A defender with two tackles must not get a card padded with blank space."""
    from PIL import Image
    import io

    sparse = PP.render_card("#4", {"Team": "Home", "Tackles": 2})
    busy = PP.render_card("#9", {"Team": "Home", "Goals": 2, "Shots": 5,
                                 "On Target": 3, "Tackles": 4, "Fouls": 1})

    h_sparse = Image.open(io.BytesIO(sparse)).height
    h_busy = Image.open(io.BytesIO(busy)).height
    assert h_busy > h_sparse


def test_a_pack_works_with_no_clips_at_all(tmp_path):
    events = [{"timestamp": START.isoformat(), "match_time": "05:00",
               "team": "Home", "action": "goal", "result": "scored",
               "player": "#9", "status": "approved"}]

    pack = PP.build_pack("#9", events, clip_results=None, out_dir=str(tmp_path))

    assert pack["clips"] == []
    assert pack["card_bytes"]
