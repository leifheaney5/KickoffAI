"""End-to-end flow tests.

Page tests assert "renders without an exception", which says nothing about
whether a page is *usable*. The UUID coercion bug that broke archiving for every
club install passed every unit test and only fell out of a full flow — these
cover that class: the sequences a coach actually performs, across module
boundaries, in order.

Deliberately driven through the real modules rather than Streamlit widgets:
`AppTest` cannot span pages, and the bugs worth catching live in the seams
between capture, archive, sync and the next match.
"""

import importlib
import os

import pytest


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A complete throwaway install: working files, library and session."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KICKOFF_CONTROL_FILE", "control.json")
    monkeypatch.setenv("KICKOFF_NOTES_FILE", "notes.json")
    monkeypatch.setenv("KICKOFF_STATUS_FILE", "status.json")
    monkeypatch.setenv("KICKOFF_DATA_FILE", "match_data.json")
    monkeypatch.setenv("KICKOFF_DB_URL", f"sqlite:///{tmp_path}/library.db")
    monkeypatch.setenv("KICKOFF_LIBRARY_ROOT", str(tmp_path / "library"))
    monkeypatch.setenv("KICKOFF_REPORTS_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("KICKOFF_SESSION_FILE", str(tmp_path / "session.json"))
    monkeypatch.delenv("KICKOFF_SHARED_DB_URL", raising=False)

    import auth
    import control
    import db
    import finalize
    import library
    import report
    import stats
    import sync
    mods = (control, stats, db, library, report, finalize, auth, sync)
    for m in mods:
        importlib.reload(m)
    yield dict(control=control, stats=stats, db=db, library=library,
               report=report, finalize=finalize, auth=auth, sync=sync,
               tmp=tmp_path)
    monkeypatch.undo()
    for m in mods:
        importlib.reload(m)


def _goal(minute, team="Home"):
    return {"timestamp": f"2026-08-19T20:{minute:02d}:00+00:00",
            "match_time": f"{minute:02d}:00", "team": team, "action": "goal",
            "result": "scored", "status": "approved", "player": "#9"}


# --------------------------------------------------------------------------- #
# Flow 1 — first run to a ready match
# --------------------------------------------------------------------------- #
def test_first_run_guides_to_readiness(app, monkeypatch):
    """A brand-new install should say what is missing, and stop once it isn't."""
    control = app["control"]
    import sys
    import types
    stub = types.ModuleType("vision_runner")
    stub.is_supported = lambda: (True, "")
    monkeypatch.setitem(sys.modules, "vision_runner", stub)

    setup = control.setup_state()
    assert setup["ready"] is False
    assert "feed" in {s["key"] for s in setup["outstanding_required"]}

    state = control.load_control()
    state["feed"]["url"] = "https://veo.example/live/index.m3u8"
    control.save_control(state)

    assert control.setup_state()["ready"] is True


# --------------------------------------------------------------------------- #
# Flow 2 — capture, archive, start the next match
# --------------------------------------------------------------------------- #
def test_match_to_archive_to_next_match(app):
    """The flow whose absence made two matches merge into one log."""
    control, stats, finalize, db = (app["control"], app["stats"],
                                    app["finalize"], app["db"])

    # --- Match 1 ---
    state = control.load_control()
    first_id = state["match_id"]
    state["match_name"] = "Eagles vs Hawks"
    state["teams"] = {"home": {"name": "Eagles", "lineup": ""},
                      "away": {"name": "Hawks", "lineup": ""}}
    control.save_control(state)
    stats.save_events([_goal(5), _goal(40, "Away")])
    control.add_written_note("back four too deep", control.load_control())

    assert control.match_phase(control.load_control()) == "finished"
    assert control.has_unsaved_work(control.load_control()) is True

    slug = finalize.finalize_match(events=stats.load_events(),
                                   state=control.load_control(), clock="90:00")
    assert slug
    assert control.match_phase(control.load_control()) == "archived"
    assert control.has_unsaved_work(control.load_control()) is False

    # --- Match 2 ---
    fresh = control.new_match(control.load_control())
    assert fresh["match_id"] != first_id
    assert stats.load_events() == []
    assert control.load_notes() == []
    assert control.match_phase(fresh) == "empty"
    # The setup you would otherwise retype survives.
    assert fresh["teams"]["home"]["name"] == "Eagles"

    stats.save_events([_goal(10)])
    finalize.finalize_match(events=stats.load_events(),
                            state=control.load_control(), clock="90:00")

    # Two distinct matches in the library, each with only its own events.
    with db.session() as s:
        rows = s.query(db.Match).all()
        assert len(rows) == 2
        assert sorted(len(m.events) for m in rows) == [1, 2]
        assert len({m.capture_id for m in rows}) == 2


def test_a_second_match_cannot_inherit_the_first_ones_events(app):
    """The exact regression: without new_match(), event logs accumulate."""
    control, stats, finalize, db = (app["control"], app["stats"],
                                    app["finalize"], app["db"])
    stats.save_events([_goal(5)])
    finalize.finalize_match(events=stats.load_events(),
                           state=control.load_control(), clock="90:00")
    control.new_match(control.load_control())

    stats.save_events(stats.load_events() + [_goal(10)])   # match 2's only goal

    assert len(stats.load_events()) == 1


# --------------------------------------------------------------------------- #
# Flow 3 — capture, sync, another user's view
# --------------------------------------------------------------------------- #
def test_capture_syncs_and_scopes_to_the_right_people(app, monkeypatch):
    control, stats, finalize, db, auth, sync = (
        app["control"], app["stats"], app["finalize"], app["db"],
        app["auth"], app["sync"])
    tmp = app["tmp"]

    admin = auth.create_user("leif", "a-good-password", "Leif")
    coach = auth.create_user("sam", "another-password", "Sam", role="coach")
    auth.start_session(admin)

    stats.save_events([_goal(5)])
    finalize.finalize_match(events=stats.load_events(),
                            state=control.load_control(), clock="90:00")

    with db.session() as s:
        m = s.query(db.Match).first()
        assert str(m.owner_id) == admin["id"]      # stamped with the capturer
        assert m.capture_id                        # and identifiable for sync

    # Offline first: nothing configured, nothing lost.
    assert sync.push()["pushed"] == 0
    assert len(sync.pending_matches()) == 1

    monkeypatch.setattr(sync, "SHARED_DB_URL", f"sqlite:///{tmp}/club.db")
    monkeypatch.setattr(sync, "SHARED_LIBRARY_ROOT", str(tmp / "club_lib"))
    assert sync.push()["pushed"] == 1
    assert sync.pending_matches() == []

    Session, _ = sync._shared_sessionmaker()
    remote = Session()
    served = remote.query(db.Match).first()
    assert auth.can_view_match(admin, served) is True
    assert auth.can_view_match(coach, served) is False   # not theirs, no team
    remote.close()


def test_an_interrupted_sync_resumes_without_duplicating(app, monkeypatch):
    """Club wifi drops. The retry must not create a second copy."""
    control, stats, finalize, db, sync = (app["control"], app["stats"],
                                          app["finalize"], app["db"], app["sync"])
    tmp = app["tmp"]
    stats.save_events([_goal(5)])
    finalize.finalize_match(events=stats.load_events(),
                            state=control.load_control(), clock="90:00")

    # First attempt: server unreachable.
    monkeypatch.setattr(sync, "SHARED_DB_URL",
                        "postgresql+psycopg://x:y@127.0.0.1:1/nope")
    res = sync.push()
    assert res.get("offline") is True
    assert [m["sync_state"] for m in sync.pending_matches()] == ["pending"]

    # Second attempt: it is back.
    monkeypatch.setattr(sync, "SHARED_DB_URL", f"sqlite:///{tmp}/club.db")
    assert sync.push()["pushed"] == 1

    Session, _ = sync._shared_sessionmaker()
    remote = Session()
    assert remote.query(db.Match).count() == 1
    assert remote.query(db.Event).count() == 1
    remote.close()


# --------------------------------------------------------------------------- #
# Flow 4 — a camera run reaches the report and the season
# --------------------------------------------------------------------------- #
def test_camera_run_flows_into_report_library_and_season(app):
    import json

    import quality as Q
    import season
    control, stats, finalize, db, report = (app["control"], app["stats"],
                                            app["finalize"], app["db"],
                                            app["report"])
    with open("match_stats.json", "w", encoding="utf-8") as fh:
        json.dump({
            "statistical_events": {
                "passing_stats": [{"passer": "A", "outcome": "completed"}] * 40,
                "possession_summary": {"team_home_percentage": 57.0,
                                       "team_away_percentage": 43.0}},
            "run_quality": {"frames_processed": 6000, "ball_detection_rate": 0.52,
                            "fps": 15.0, "reconnects": 0, "calibrated": True},
        }, fh)

    vision = report.load_vision("match_stats.json")
    assert Q.is_trustworthy(vision["quality"]) is True

    stats.save_events([_goal(5)])
    state = control.load_control()
    state["teams"] = {"home": {"name": "Eagles", "lineup": ""},
                      "away": {"name": "Hawks", "lineup": ""}}
    control.save_control(state)
    finalize.finalize_match(events=stats.load_events(),
                            state=control.load_control(), clock="90:00")

    with db.session() as s:
        m = s.query(db.Match).first()
        assert m.vision_verdict == "measured"
        assert m.vision_home_possession == 57.0
        rows = [{"played_on": m.played_on, "home_team": m.home_team,
                 "away_team": m.away_team, "vision_verdict": m.vision_verdict,
                 "vision_ball_rate": m.vision_ball_rate,
                 "vision_home_possession": m.vision_home_possession,
                 "vision_away_possession": m.vision_away_possession}]

    assert season.vision_coverage(rows)["measured"] == 1
    assert len(season.possession_trend(rows)) == 1


def test_an_indicative_run_is_kept_out_of_season_trends(app):
    """The trust gate's whole purpose, verified across the full flow."""
    import json

    import season
    control, stats, finalize, db = (app["control"], app["stats"],
                                    app["finalize"], app["db"])
    with open("match_stats.json", "w", encoding="utf-8") as fh:
        json.dump({
            "statistical_events": {
                "passing_stats": [],
                "possession_summary": {"team_home_percentage": 80.0,
                                       "team_away_percentage": 20.0}},
            "run_quality": {"frames_processed": 6000, "ball_detection_rate": 0.15,
                            "fps": 15.0, "reconnects": 0, "calibrated": False},
        }, fh)

    stats.save_events([_goal(5)])
    finalize.finalize_match(events=stats.load_events(),
                            state=control.load_control(), clock="90:00")

    with db.session() as s:
        m = s.query(db.Match).first()
        assert m.vision_verdict == "indicative"
        rows = [{"played_on": m.played_on, "home_team": m.home_team,
                 "away_team": m.away_team, "vision_verdict": m.vision_verdict,
                 "vision_ball_rate": m.vision_ball_rate,
                 "vision_home_possession": m.vision_home_possession,
                 "vision_away_possession": m.vision_away_possession}]

    # It is archived and visible on its own report, but must not skew the season.
    assert season.possession_trend(rows) == []
    assert season.vision_coverage(rows)["indicative"] == 1
