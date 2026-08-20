"""Tests for the club features: auth, ownership scoping, and offline sync.

Auth is security-sensitive, so the properties that matter are asserted directly:
passwords are never recoverable, sessions are not replayable from disk, and a
missing user cannot be distinguished from a wrong password.
"""

import importlib
import json
import os
import time

import pytest


@pytest.fixture
def club(tmp_path, monkeypatch):
    """A throwaway local library + session file."""
    monkeypatch.setenv("KICKOFF_DB_URL", f"sqlite:///{tmp_path}/local.db")
    monkeypatch.setenv("KICKOFF_LIBRARY_ROOT", str(tmp_path / "lib"))
    monkeypatch.setenv("KICKOFF_SESSION_FILE", str(tmp_path / "session.json"))
    monkeypatch.delenv("KICKOFF_SHARED_DB_URL", raising=False)

    import auth
    import db
    import library
    import sync
    for m in (db, library, auth, sync):
        importlib.reload(m)
    yield db, library, auth, sync, tmp_path
    monkeypatch.undo()
    for m in (db, library, auth, sync):
        importlib.reload(m)


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def test_password_hash_is_not_reversible(club):
    _, _, auth, _, _ = club
    encoded = auth.hash_password("correct-horse-battery")

    assert "correct-horse-battery" not in encoded
    assert encoded.startswith("pbkdf2_sha256$")
    assert auth.verify_password("correct-horse-battery", encoded) is True
    assert auth.verify_password("wrong", encoded) is False


def test_same_password_hashes_differently_each_time(club):
    """Per-user salt: two users with one password must not share a hash."""
    _, _, auth, _, _ = club

    assert auth.hash_password("same-password") != auth.hash_password("same-password")


def test_malformed_hashes_are_rejected_not_crashed(club):
    _, _, auth, _, _ = club

    for junk in ("", "nonsense", "md5$1$a$b", "pbkdf2_sha256$notanint$a$b"):
        assert auth.verify_password("x", junk) is False


def test_weak_passwords_are_refused(club):
    _, _, auth, _, _ = club

    assert auth.password_problem("short") is not None
    assert auth.password_problem("password") is not None
    assert auth.password_problem("a-perfectly-fine-one") is None


# --------------------------------------------------------------------------- #
# Users and sign-in
# --------------------------------------------------------------------------- #
def test_auth_is_off_until_the_first_account_exists(club):
    """A single-coach install must never be asked to log in."""
    _, _, auth, _, _ = club

    assert auth.auth_enabled() is False
    assert auth.current_user() is None

    auth.create_user("leif", "a-good-password")
    assert auth.auth_enabled() is True


def test_the_first_user_becomes_admin(club):
    _, _, auth, _, _ = club

    first = auth.create_user("leif", "a-good-password")
    second = auth.create_user("assistant", "another-password", role="coach")

    assert first["role"] == "admin"      # someone must be able to administer
    assert second["role"] == "coach"


def test_duplicate_usernames_are_refused(club):
    _, _, auth, _, _ = club
    auth.create_user("leif", "a-good-password")

    with pytest.raises(ValueError):
        auth.create_user("leif", "another-password")


def test_authenticate_accepts_only_the_right_password(club):
    _, _, auth, _, _ = club
    auth.create_user("leif", "a-good-password")

    assert auth.authenticate("leif", "a-good-password")["username"] == "leif"
    assert auth.authenticate("leif", "wrong") is None
    assert auth.authenticate("ghost", "a-good-password") is None


def test_usernames_are_case_insensitive(club):
    _, _, auth, _, _ = club
    auth.create_user("Leif", "a-good-password")

    assert auth.authenticate("LEIF", "a-good-password") is not None


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
def test_session_file_never_stores_a_usable_token(club, tmp_path):
    """Reading the session file must not hand over a working session."""
    _, _, auth, _, _ = club
    user = auth.create_user("leif", "a-good-password")

    token = auth.start_session(user)
    on_disk = (tmp_path / "session.json").read_text(encoding="utf-8")

    assert token not in on_disk
    assert json.loads(on_disk)["token_sha256"] != token


def test_session_file_is_not_world_readable(club, tmp_path):
    _, _, auth, _, _ = club
    auth.start_session(auth.create_user("leif", "a-good-password"))

    mode = os.stat(tmp_path / "session.json").st_mode & 0o777
    assert mode == 0o600


def test_a_wrong_token_is_rejected(club):
    _, _, auth, _, _ = club
    auth.start_session(auth.create_user("leif", "a-good-password"))

    assert auth.current_user("not-the-token") is None


def test_sign_out_ends_the_session(club):
    _, _, auth, _, _ = club
    token = auth.start_session(auth.create_user("leif", "a-good-password"))
    assert auth.current_user(token) is not None

    auth.end_session()
    assert auth.current_user(token) is None


def test_an_expired_session_is_not_accepted(club, monkeypatch):
    _, _, auth, _, _ = club
    token = auth.start_session(auth.create_user("leif", "a-good-password"))

    # Read the real clock before patching it. os.times().elapsed happens to be
    # epoch time on macOS but is seconds-since-boot on Linux, which put the fake
    # "now" decades in the past -- so this never tested expiry on CI at all.
    expired_at = time.time() + auth.SESSION_TTL + 10_000
    monkeypatch.setattr(auth.time, "time", lambda: expired_at)
    assert auth.current_user(token) is None


# --------------------------------------------------------------------------- #
# Visibility scoping
# --------------------------------------------------------------------------- #
class _FakeMatch:
    def __init__(self, owner_id=None, team_id=None):
        self.owner_id, self.team_id = owner_id, team_id


def test_everything_is_visible_when_auth_is_off(club):
    _, _, auth, _, _ = club

    assert auth.can_view_match(None, _FakeMatch(owner_id="someone")) is True


def test_a_coach_sees_their_own_matches(club):
    _, _, auth, _, _ = club
    auth.create_user("admin", "a-good-password")
    coach = auth.create_user("coach", "another-password", role="coach")

    assert auth.can_view_match(coach, _FakeMatch(owner_id=coach["id"])) is True
    assert auth.can_view_match(coach, _FakeMatch(owner_id="somebody-else")) is False


def test_unowned_matches_stay_visible(club):
    """Matches archived before club mode must not vanish behind a migration."""
    _, _, auth, _, _ = club
    auth.create_user("admin", "a-good-password")
    coach = auth.create_user("coach", "another-password", role="coach")

    assert auth.can_view_match(coach, _FakeMatch()) is True


def test_an_admin_sees_everything(club):
    _, _, auth, _, _ = club
    admin = auth.create_user("admin", "a-good-password")

    assert auth.can_view_match(admin, _FakeMatch(owner_id="anyone")) is True


def test_ids_coerce_to_uuid_for_the_database(club):
    """User dicts carry string ids; the columns are UUID-typed.

    Assigning the raw string raises on flush, which would have broken archiving
    for every club install.
    """
    import uuid as _uuid
    _, _, auth, _, _ = club
    user = auth.create_user("leif", "a-good-password")

    coerced = auth.as_uuid(user["id"])
    assert isinstance(coerced, _uuid.UUID)
    assert str(coerced) == user["id"]
    assert auth.as_uuid(coerced) is coerced        # idempotent
    assert auth.as_uuid(None) is None
    assert auth.as_uuid("not-a-uuid") is None


def test_owner_id_can_actually_be_written_to_a_match(club):
    """Regression: the write path, not just the helper."""
    db, library, auth, _, _ = club
    user = auth.create_user("leif", "a-good-password")
    db.init_db()

    with db.session() as s:
        m = library.create_match(s, "Eagles vs Hawks", None, "Eagles", "Hawks",
                                 1, 0, "")
        m.owner_id = auth.as_uuid(user["id"])      # must survive the flush
        s.flush()

    with db.session() as s:
        assert str(s.query(db.Match).first().owner_id) == user["id"]


def test_team_membership_grants_visibility(club):
    db, _, auth, _, _ = club
    auth.create_user("admin", "a-good-password")
    coach = auth.create_user("coach", "another-password", role="coach")
    db.init_db()
    with db.session() as s:
        team = db.Team(slug="u14", name="U14")
        s.add(team)
        s.flush()
        team_id = team.id
        s.add(db.TeamMember(user_id=auth.as_uuid(coach["id"]), team_id=team_id))

    assert auth.can_view_match(coach, _FakeMatch(team_id=team_id)) is True
    # ...but not another team's match.
    import uuid as _uuid
    assert auth.can_view_match(coach, _FakeMatch(team_id=_uuid.uuid4())) is False


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #
def _archive(db, library, capture_id, name="Match"):
    db.init_db()
    with db.session() as s:
        m = library.create_match(s, name, None, "Eagles", "Hawks", 1, 0, "")
        m.capture_id = capture_id
        s.flush()
        s.add(db.Event(match_id=m.id, action="goal", team="Home", source="audio"))
        return str(m.id)


def test_sync_is_a_no_op_without_a_server(club):
    """No club configured must not look like a failure."""
    db, library, _, sync, _ = club
    _archive(db, library, "cap-a")

    assert sync.configured() is False
    res = sync.push()
    assert res["ok"] is False
    assert res["pushed"] == 0


def test_unreachable_server_marks_pending_and_loses_nothing(club, monkeypatch):
    db, library, _, sync, _ = club
    _archive(db, library, "cap-a")
    monkeypatch.setattr(sync, "SHARED_DB_URL",
                        "postgresql+psycopg://x:y@127.0.0.1:1/nope")

    res = sync.push()

    assert res.get("offline") is True
    assert res["pushed"] == 0
    assert [m["sync_state"] for m in sync.pending_matches()] == ["pending"]


def test_push_copies_matches_and_events(club, monkeypatch, tmp_path):
    db, library, _, sync, _ = club
    _archive(db, library, "cap-a", "First")
    _archive(db, library, "cap-b", "Second")
    monkeypatch.setattr(sync, "SHARED_DB_URL", f"sqlite:///{tmp_path}/club.db")

    res = sync.push()

    assert res["ok"] is True and res["pushed"] == 2
    assert sync.pending_matches() == []
    Session, _ = sync._shared_sessionmaker()
    remote = Session()
    assert remote.query(db.Match).count() == 2
    assert remote.query(db.Event).count() == 2
    remote.close()


def test_pushing_twice_cannot_duplicate_a_match(club, monkeypatch, tmp_path):
    """The invariant the whole sync design rests on: capture_id is identity."""
    db, library, _, sync, _ = club
    _archive(db, library, "cap-a")
    monkeypatch.setattr(sync, "SHARED_DB_URL", f"sqlite:///{tmp_path}/club.db")
    sync.push()

    with db.session() as s:                 # force a re-push, as a retry would
        for m in s.query(db.Match).all():
            m.sync_state = "local"
    res = sync.push()

    assert [r["action"] for r in res["results"]] == ["updated"]
    Session, _ = sync._shared_sessionmaker()
    remote = Session()
    assert remote.query(db.Match).count() == 1      # not 2
    assert remote.query(db.Event).count() == 1      # not 2
    remote.close()


def test_slug_collisions_are_disambiguated_not_dropped(club, monkeypatch, tmp_path):
    """Two coaches can generate the same slug for different fixtures."""
    db, library, _, sync, _ = club
    db.init_db()
    monkeypatch.setattr(sync, "SHARED_DB_URL", f"sqlite:///{tmp_path}/club.db")

    # Another coach already pushed a match that happens to slugify identically.
    Session, _ = sync._shared_sessionmaker()
    remote = Session()
    remote.add(db.Match(slug="clash", name="Someone else's",
                        capture_id="other-machine"))
    remote.commit()
    remote.close()

    with db.session() as s:
        m = library.create_match(s, "Eagles vs Hawks", None, "Eagles", "Hawks",
                                 1, 0, "")
        m.slug = "clash"
        m.capture_id = "my-machine"

    res = sync.push()

    assert res["pushed"] == 1
    remote = Session()
    slugs = sorted(r.slug for r in remote.query(db.Match).all())
    assert slugs == ["clash", "clash-2"]      # disambiguated, neither lost
    remote.close()


def test_redacted_url_hides_the_password(club, monkeypatch):
    _, _, _, sync, _ = club
    monkeypatch.setattr(sync, "SHARED_DB_URL",
                        "postgresql+psycopg://kickoff:s3cret@club.local:5432/kickoff")

    shown = sync._redacted_url()

    assert "s3cret" not in shown
    assert "club.local" in shown


# --------------------------------------------------------------------------- #
# Media sync (the artifacts, not just the numbers)
# --------------------------------------------------------------------------- #
def _match_with_media(db, library, tmp_path, capture_id="cap-m"):
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "report.pdf").write_bytes(b"PDF" * 1000)
    (src / "match.mp4").write_bytes(b"\0" * (2 * 1024 * 1024))
    db.init_db()
    with db.session() as s:
        m = library.create_match(s, "Eagles vs Hawks", None, "Eagles", "Hawks",
                                 1, 0, "")
        m.capture_id = capture_id
        s.flush()
        library.register_file(s, m, "report_pdf", str(src / "report.pdf"), "Report")
        library.register_file(s, m, "video", str(src / "match.mp4"), "Video")


def test_reports_sync_but_video_stays_local_by_default(club, monkeypatch, tmp_path):
    """The club library must have the documents; wifi must not carry the video."""
    db, library, _, sync, _ = club
    _match_with_media(db, library, tmp_path)
    monkeypatch.setattr(sync, "SHARED_DB_URL", f"sqlite:///{tmp_path}/club.db")
    monkeypatch.setattr(sync, "SHARED_LIBRARY_ROOT", str(tmp_path / "club_lib"))

    res = sync.push()

    media = res["results"][0]["media"]
    assert media["copied"] == 1
    assert any("video" in r for r in media["reasons"])
    on_server = [f for _r, _d, fs in os.walk(tmp_path / "club_lib") for f in fs]
    assert "report.pdf" in on_server
    assert "match.mp4" not in on_server


def test_video_syncs_when_explicitly_enabled(club, monkeypatch, tmp_path):
    db, library, _, sync, _ = club
    _match_with_media(db, library, tmp_path)
    monkeypatch.setattr(sync, "SHARED_DB_URL", f"sqlite:///{tmp_path}/club.db")
    monkeypatch.setattr(sync, "SHARED_LIBRARY_ROOT", str(tmp_path / "club_lib"))
    monkeypatch.setattr(sync, "SYNC_LARGE_MEDIA", True)

    sync.push()

    on_server = [f for _r, _d, fs in os.walk(tmp_path / "club_lib") for f in fs]
    assert "match.mp4" in on_server


def test_oversized_files_are_skipped_with_a_reason(club, monkeypatch, tmp_path):
    """One huge upload must not stall a sync that would otherwise succeed."""
    db, library, _, sync, _ = club
    _match_with_media(db, library, tmp_path)
    monkeypatch.setattr(sync, "SHARED_DB_URL", f"sqlite:///{tmp_path}/club.db")
    monkeypatch.setattr(sync, "SHARED_LIBRARY_ROOT", str(tmp_path / "club_lib"))
    monkeypatch.setattr(sync, "SYNC_LARGE_MEDIA", True)
    monkeypatch.setattr(sync, "MEDIA_MAX_MB", 1.0)      # the video is 2 MB

    res = sync.push()

    media = res["results"][0]["media"]
    assert media["copied"] == 1                          # the report still went
    assert any("over the" in r for r in media["reasons"])


def test_pushing_media_twice_does_not_duplicate_rows(club, monkeypatch, tmp_path):
    db, library, _, sync, _ = club
    _match_with_media(db, library, tmp_path)
    monkeypatch.setattr(sync, "SHARED_DB_URL", f"sqlite:///{tmp_path}/club.db")
    monkeypatch.setattr(sync, "SHARED_LIBRARY_ROOT", str(tmp_path / "club_lib"))
    sync.push()

    with db.session() as s:                              # force a retry
        for m in s.query(db.Match).all():
            m.sync_state = "local"
    sync.push()

    Session, _ = sync._shared_sessionmaker()
    remote = Session()
    assert remote.query(db.MediaFile).count() == 1
    remote.close()


def test_media_failure_does_not_lose_the_match(club, monkeypatch, tmp_path):
    """The match row is committed first; a broken copy must not undo it."""
    db, library, _, sync, _ = club
    _match_with_media(db, library, tmp_path)
    monkeypatch.setattr(sync, "SHARED_DB_URL", f"sqlite:///{tmp_path}/club.db")
    monkeypatch.setattr(sync, "SHARED_LIBRARY_ROOT", str(tmp_path / "club_lib"))

    def boom(*a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr(sync, "_copy_media", boom)

    res = sync.push()

    assert res["pushed"] == 1                            # match still landed
    Session, _ = sync._shared_sessionmaker()
    remote = Session()
    assert remote.query(db.Match).count() == 1
    remote.close()
    assert sync.pending_matches() == []                  # and is marked synced


def test_media_sync_is_off_without_a_shared_root(club, monkeypatch, tmp_path):
    db, library, _, sync, _ = club
    _match_with_media(db, library, tmp_path)
    monkeypatch.setattr(sync, "SHARED_DB_URL", f"sqlite:///{tmp_path}/club.db")
    monkeypatch.setattr(sync, "SHARED_LIBRARY_ROOT", "")

    res = sync.push()

    assert res["pushed"] == 1
    assert res["results"][0]["media"]["copied"] == 0


# --------------------------------------------------------------------------- #
# Sideline view access
#
# The sideline view is the one surface reachable from outside the machine, so
# who can open it is asserted directly.
# --------------------------------------------------------------------------- #
def test_localhost_only_needs_no_code(club, monkeypatch):
    """Bound to 127.0.0.1 there is nobody to keep out."""
    _, _, auth, _, _ = club
    monkeypatch.delenv("KICKOFF_LAN", raising=False)
    monkeypatch.delenv("KICKOFF_SIDELINE_CODE", raising=False)

    assert auth.lan_enabled() is False
    assert auth.sideline_code() == ""
    assert auth.sideline_allowed()[0] is True


def test_lan_mode_requires_a_code(club, monkeypatch):
    """Binding to the wifi should be a decision, not a surprise."""
    _, _, auth, _, _ = club
    monkeypatch.setenv("KICKOFF_LAN", "1")
    monkeypatch.setenv("KICKOFF_SIDELINE_CODE", "match-day")

    ok, why = auth.sideline_allowed()
    assert ok is False and "code" in why.lower()
    assert auth.sideline_allowed("wrong")[0] is False
    assert auth.sideline_allowed("match-day")[0] is True


def test_lan_mode_generates_a_code_when_none_is_set(club, monkeypatch):
    """Never silently open: an unset code becomes a generated one."""
    _, _, auth, _, _ = club
    monkeypatch.setenv("KICKOFF_LAN", "1")
    monkeypatch.delenv("KICKOFF_SIDELINE_CODE", raising=False)
    monkeypatch.setattr(auth, "_EPHEMERAL_CODE", None)

    code = auth.sideline_code()
    assert len(code) == 6 and code.isdigit()
    assert auth.sideline_code() == code          # stable for the process
    assert auth.sideline_allowed(code)[0] is True
    assert auth.sideline_allowed("000000" if code != "000000" else "111111")[0] is False


def test_club_mode_supersedes_the_code(club, monkeypatch):
    """With accounts in use, sign-in is the gate — not a shared secret."""
    _, _, auth, _, _ = club
    monkeypatch.setenv("KICKOFF_LAN", "1")
    monkeypatch.setenv("KICKOFF_SIDELINE_CODE", "match-day")
    user = auth.create_user("leif", "a-good-password")

    ok, why = auth.sideline_allowed("match-day")
    assert ok is False and "sign in" in why.lower()   # a code is not enough

    auth.start_session(user)
    assert auth.sideline_allowed()[0] is True         # signed in needs no code
