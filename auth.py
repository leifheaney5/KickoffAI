#!/usr/bin/env python3
"""
Kickoff Pulse — authentication for a shared club install.

Scope, stated plainly: this is **LAN-appropriate authentication for a
self-hosted club server**. It keeps club members' matches separated and stops
casual access. It is *not* hardened for exposure to the open internet — that
would additionally need TLS termination, rate limiting on login, account
lockout, and a security review. Do not publish the Postgres port or the
Streamlit port to the internet on the strength of this module.

What it does do properly:
  * passwords are stored only as PBKDF2-HMAC-SHA256 with a per-user random salt
    and a high iteration count — never plaintext, never reversible
  * comparisons use `hmac.compare_digest`, so a wrong password cannot be found
    by timing
  * session tokens are 256 bits from `secrets.token_urlsafe` and are stored
    hashed, so a leaked session file cannot be replayed against the server
  * single-user installs stay frictionless: with no users defined, auth is off

No third-party crypto: `hashlib.pbkdf2_hmac` is in the standard library and is
the right tool here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

import db

# PBKDF2 cost. 600k matches OWASP's 2023 guidance for SHA-256 and takes a few
# hundred milliseconds — unnoticeable on a login, expensive in bulk for anyone
# who steals the table.
PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 16
TOKEN_BYTES = 32

# Where a signed-in session is remembered on this machine. Per-machine, not in
# the repo: a capture laptop stays signed in between launches.
SESSION_FILE = os.environ.get(
    "KICKOFF_SESSION_FILE",
    os.path.join(os.path.expanduser("~"), ".kickoff_session.json"))

SESSION_TTL = float(os.environ.get("KICKOFF_SESSION_TTL", 60 * 60 * 24 * 30))

ROLES = ("admin", "coach")


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def hash_password(password: str, *, salt: bytes = None,
                  iterations: int = PBKDF2_ITERATIONS) -> str:
    """Hash a password into a self-describing `pbkdf2_sha256$iters$salt$hash`."""
    if not password:
        raise ValueError("A password is required.")
    salt = salt or secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                             iterations)
    return "$".join((
        "pbkdf2_sha256", str(iterations),
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    ))


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check of a password against a stored hash."""
    if not password or not encoded:
        return False
    try:
        scheme, iters, salt_b64, hash_b64 = encoded.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"),
            base64.b64decode(salt_b64), int(iters))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(base64.b64encode(dk).decode("ascii"), hash_b64)


def password_problem(password: str) -> str | None:
    """Return why a password is unacceptable, or None if it is fine."""
    if not password or len(password) < 8:
        return "Use at least 8 characters."
    if password.lower() in {"password", "kickoff", "12345678", "letmein"}:
        return "That password is too common."
    return None


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def auth_enabled() -> bool:
    """True once any user exists.

    A single-coach install never creates one and is never asked to log in —
    club features are opt-in, not a tax on the original use case.
    """
    try:
        db.init_db()
        with db.session() as s:
            return s.query(db.User).count() > 0
    except Exception:
        return False


def create_user(username: str, password: str, display_name: str = "",
                role: str = "coach") -> dict:
    """Create a user. The first user created is always an admin."""
    username = (username or "").strip().lower()
    if not username:
        raise ValueError("A username is required.")
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    if role not in ROLES:
        raise ValueError(f"Unknown role {role!r}.")

    db.init_db()
    with db.session() as s:
        if s.query(db.User).filter_by(username=username).first():
            raise ValueError(f"User {username!r} already exists.")
        # Bootstrapping: someone has to be able to administer the club.
        if s.query(db.User).count() == 0:
            role = "admin"
        user = db.User(username=username, display_name=display_name or username,
                       password_hash=hash_password(password), role=role)
        s.add(user)
        s.flush()
        return _as_dict(user)


def set_password(username: str, password: str) -> None:
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    with db.session() as s:
        user = s.query(db.User).filter_by(username=(username or "").lower()).first()
        if not user:
            raise ValueError("No such user.")
        user.password_hash = hash_password(password)


def list_users() -> list[dict]:
    db.init_db()
    with db.session() as s:
        return [_as_dict(u) for u in s.query(db.User).order_by(db.User.username)]


def _as_dict(user) -> dict:
    return {"id": str(user.id), "username": user.username,
            "display_name": user.display_name, "role": user.role,
            "active": bool(user.active)}


def as_uuid(value):
    """Coerce an id to a real UUID for a database column, or None.

    User dicts carry ids as strings (they cross JSON in the session file), but
    the ORM columns are UUID-typed — assigning the string raises on flush. Every
    write of an id goes through here.
    """
    import uuid as _uuid

    if value is None or isinstance(value, _uuid.UUID):
        return value
    try:
        return _uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Sign in / sessions
# --------------------------------------------------------------------------- #
_DUMMY_HASH = None


def _dummy_hash() -> str:
    """A fixed hash to verify against when the user does not exist.

    Computed once and cached. It must be *verified* (one PBKDF2 pass), not
    re-hashed — hashing would run PBKDF2 twice and make the unknown-user path
    measurably slower than a wrong password, which is the enumeration leak this
    is meant to close.
    """
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("kickoff-pulse-dummy-password")
    return _DUMMY_HASH


def authenticate(username: str, password: str) -> dict | None:
    """Check credentials. Returns the user dict, or None."""
    db.init_db()
    with db.session() as s:
        user = s.query(db.User).filter_by(
            username=(username or "").strip().lower()).first()
        if user is None or not user.active:
            # One verify, matching the cost of the real path, so a missing user
            # cannot be told from a wrong password by how long the answer takes.
            verify_password(password or "", _dummy_hash())
            return None
        if not verify_password(password or "", user.password_hash):
            return None
        user.last_seen_at = db._utcnow()
        return _as_dict(user)


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def start_session(user: dict) -> str:
    """Persist a signed-in session on this machine and return its token."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    payload = {
        "user": user,
        # Only the fingerprint is stored: the raw token never touches disk, so
        # reading this file does not hand over a usable session.
        "token_sha256": _token_fingerprint(token),
        "created_at": time.time(),
    }
    tmp = SESSION_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.chmod(tmp, 0o600)          # not world-readable
        os.replace(tmp, SESSION_FILE)
    except OSError:
        pass
    return token


def current_user(token: str = None) -> dict | None:
    """The signed-in user for this machine, or None.

    With no users defined this returns None and callers should treat the app as
    unrestricted — a single-coach install behaves exactly as it always has.
    """
    if not auth_enabled():
        return None
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    if time.time() - float(payload.get("created_at", 0)) > SESSION_TTL:
        end_session()
        return None
    if token is not None and not hmac.compare_digest(
            _token_fingerprint(token), payload.get("token_sha256", "")):
        return None
    user = payload.get("user")
    return user if isinstance(user, dict) else None


def end_session() -> None:
    try:
        os.remove(SESSION_FILE)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Authorisation
# --------------------------------------------------------------------------- #
def is_admin(user: dict) -> bool:
    return bool(user) and user.get("role") == "admin"


def team_ids_for(user: dict) -> list[str]:
    """Teams this user may see. Admins see everything (signalled by None)."""
    if not user:
        return []
    if is_admin(user):
        return []          # empty == unrestricted for admins; see visible_match_ids
    with db.session() as s:
        rows = s.query(db.TeamMember.team_id).filter_by(
            user_id=as_uuid(user["id"])).all()
        return [str(r[0]) for r in rows]


def can_view_match(user: dict, match) -> bool:
    """Whether `user` may see a match row.

    Unowned matches (archived before club features existed) stay visible to
    everyone — hiding a coach's own history behind a migration would be worse
    than the mild over-sharing.
    """
    if not auth_enabled() or user is None:
        return True
    if is_admin(user):
        return True
    owner = getattr(match, "owner_id", None)
    team = getattr(match, "team_id", None)
    if owner is None and team is None:
        return True
    if owner is not None and str(owner) == user["id"]:
        return True
    return team is not None and str(team) in set(team_ids_for(user))
