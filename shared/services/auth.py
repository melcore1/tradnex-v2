"""Phase 6 auth: user CRUD, password hashing, session lifecycle, login
rate-limit. Single-user / DB-backed; no JWT, no signed cookies.

Sessions are random UUIDs stored in `sessions` (FK → users). The cookie
holds only the UUID; auth = look up the row, verify not expired/revoked,
update `last_activity_ts`. Logout = revoke a single session;
revoke_all_sessions does the same across every active row for a user.

Rate-limit logic counts FAILED `login_attempts` rows for the given email
in the last LOGIN_LOCKOUT_WINDOW_SECONDS. ≥ LOGIN_LOCKOUT_THRESHOLD
failures → AccountLockedError until LOGIN_LOCKOUT_DURATION_SECONDS
after the most recent failure. Successful logins do NOT clear earlier
failures (the audit trail stays intact); they just stop adding new ones.
"""

from __future__ import annotations

import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import bcrypt
from pydantic import BaseModel, ConfigDict


class AuthError(Exception):
    """Base for all auth errors."""


class AccountLockedError(AuthError):
    """Raised when too many recent failed logins; includes retry_after_s."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"Account locked, retry in {retry_after_s}s")
        self.retry_after_s = retry_after_s


class UserExistsError(AuthError):
    """create_user found an existing email."""


class User(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    email: str
    created_ts: datetime
    last_login_ts: datetime | None = None


class Session(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    user_id: int
    created_ts: datetime
    expires_ts: datetime
    last_activity_ts: datetime
    user_agent: str | None = None
    ip_address: str | None = None
    revoked: bool = False

    @property
    def is_valid(self) -> bool:
        return (
            not self.revoked
            and self.expires_ts > datetime.now(UTC)
        )


@dataclass(frozen=True)
class RateLimitConfig:
    threshold: int
    window_seconds: int
    duration_seconds: int


# ---- password hashing ----


def hash_password(password: str) -> str:
    """bcrypt with cost factor 12 (default)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---- user CRUD ----


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=int(row["id"]),
        email=row["email"],
        created_ts=datetime.fromtimestamp(float(row["created_ts"]), tz=UTC),
        last_login_ts=(
            datetime.fromtimestamp(float(row["last_login_ts"]), tz=UTC)
            if row["last_login_ts"] is not None
            else None
        ),
    )


async def create_user(
    conn: sqlite3.Connection,
    email: str,
    password: str,
) -> User:
    """Create a new user. Raises UserExistsError if email already in use."""
    email_norm = email.strip().lower()
    existing = conn.execute(
        "SELECT id FROM users WHERE email = ?", (email_norm,)
    ).fetchone()
    if existing is not None:
        raise UserExistsError(f"User with email '{email_norm}' already exists")

    now_ts = time.time()
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, created_ts) VALUES (?, ?, ?)",
        (email_norm, hash_password(password), now_ts),
    )
    conn.commit()
    new_id = cur.lastrowid
    if new_id is None:
        raise RuntimeError("Failed to insert users row")
    row = conn.execute(
        "SELECT id, email, created_ts, last_login_ts FROM users WHERE id = ?",
        (new_id,),
    ).fetchone()
    return _row_to_user(row)


async def get_user_by_email(
    conn: sqlite3.Connection, email: str
) -> User | None:
    row = conn.execute(
        "SELECT id, email, created_ts, last_login_ts FROM users "
        "WHERE email = ?",
        (email.strip().lower(),),
    ).fetchone()
    if row is None:
        return None
    return _row_to_user(row)


async def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> User | None:
    row = conn.execute(
        "SELECT id, email, created_ts, last_login_ts FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_user(row)


async def list_users(conn: sqlite3.Connection) -> list[User]:
    rows = conn.execute(
        "SELECT id, email, created_ts, last_login_ts FROM users "
        "ORDER BY created_ts ASC"
    ).fetchall()
    return [_row_to_user(r) for r in rows]


# ---- rate-limit ----


def _count_recent_failures(
    conn: sqlite3.Connection,
    email: str,
    window_seconds: int,
) -> tuple[int, float | None]:
    """Returns (failure_count, latest_failure_ts) within the window."""
    cutoff = time.time() - window_seconds
    row = conn.execute(
        "SELECT COUNT(*) AS c, MAX(timestamp) AS latest FROM login_attempts "
        "WHERE email = ? AND success = 0 AND timestamp >= ?",
        (email.strip().lower(), cutoff),
    ).fetchone()
    return int(row["c"]), (float(row["latest"]) if row["latest"] is not None else None)


def _record_attempt(
    conn: sqlite3.Connection,
    email: str,
    ip_address: str | None,
    success: bool,
) -> None:
    conn.execute(
        "INSERT INTO login_attempts (email, ip_address, success, timestamp) "
        "VALUES (?, ?, ?, ?)",
        (email.strip().lower(), ip_address, 1 if success else 0, time.time()),
    )
    conn.commit()


def check_lockout(
    conn: sqlite3.Connection,
    email: str,
    cfg: RateLimitConfig,
) -> int | None:
    """Return remaining lockout seconds, or None if not locked."""
    count, latest = _count_recent_failures(conn, email, cfg.window_seconds)
    if count < cfg.threshold or latest is None:
        return None
    elapsed = time.time() - latest
    remaining = int(cfg.duration_seconds - elapsed)
    return remaining if remaining > 0 else None


# ---- authenticate + sessions ----


async def authenticate(
    conn: sqlite3.Connection,
    email: str,
    password: str,
    ip_address: str | None,
    cfg: RateLimitConfig,
) -> User | None:
    """Verify credentials. Returns User on success, None on bad password.
    Raises AccountLockedError if currently locked. Always records the attempt.
    """
    locked_for = check_lockout(conn, email, cfg)
    if locked_for is not None:
        # Still record the attempt for the audit trail.
        _record_attempt(conn, email, ip_address, success=False)
        raise AccountLockedError(retry_after_s=locked_for)

    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE email = ?",
        (email.strip().lower(),),
    ).fetchone()
    if row is None:
        # Same record-attempt path as bad password; no enumeration.
        _record_attempt(conn, email, ip_address, success=False)
        return None

    if not verify_password(password, row["password_hash"]):
        _record_attempt(conn, email, ip_address, success=False)
        return None

    # Success: update last_login_ts, clear failed_login_count
    conn.execute(
        "UPDATE users SET last_login_ts = ?, failed_login_count = 0 WHERE id = ?",
        (time.time(), int(row["id"])),
    )
    conn.commit()
    _record_attempt(conn, email, ip_address, success=True)

    user = await get_user_by_id(conn, int(row["id"]))
    assert user is not None
    return user


async def create_session(
    conn: sqlite3.Connection,
    user: User,
    *,
    duration_seconds: int,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> Session:
    session_id = secrets.token_urlsafe(32)
    now_ts = time.time()
    expires_ts = now_ts + duration_seconds
    conn.execute(
        "INSERT INTO sessions (id, user_id, created_ts, expires_ts, "
        "last_activity_ts, user_agent, ip_address) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            user.id,
            now_ts,
            expires_ts,
            now_ts,
            user_agent,
            ip_address,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, user_id, created_ts, expires_ts, last_activity_ts, "
        "user_agent, ip_address, revoked FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    return _row_to_session(row)


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        user_id=int(row["user_id"]),
        created_ts=datetime.fromtimestamp(float(row["created_ts"]), tz=UTC),
        expires_ts=datetime.fromtimestamp(float(row["expires_ts"]), tz=UTC),
        last_activity_ts=datetime.fromtimestamp(
            float(row["last_activity_ts"]), tz=UTC
        ),
        user_agent=row["user_agent"],
        ip_address=row["ip_address"],
        revoked=bool(int(row["revoked"])),
    )


async def get_session(
    conn: sqlite3.Connection, session_id: str
) -> Session | None:
    """Return the session if valid; touch last_activity_ts. None when
    missing / expired / revoked."""
    row = conn.execute(
        "SELECT id, user_id, created_ts, expires_ts, last_activity_ts, "
        "user_agent, ip_address, revoked FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    session = _row_to_session(row)
    if not session.is_valid:
        return None
    # Touch activity (cheap, single UPDATE)
    conn.execute(
        "UPDATE sessions SET last_activity_ts = ? WHERE id = ?",
        (time.time(), session_id),
    )
    conn.commit()
    return session


async def revoke_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "UPDATE sessions SET revoked = 1 WHERE id = ?",
        (session_id,),
    )
    conn.commit()


async def revoke_all_sessions(
    conn: sqlite3.Connection, user_id: int
) -> int:
    cur = conn.execute(
        "UPDATE sessions SET revoked = 1 WHERE user_id = ? AND revoked = 0",
        (user_id,),
    )
    conn.commit()
    return int(cur.rowcount)


async def cleanup_expired_sessions(conn: sqlite3.Connection) -> int:
    """Maintenance: delete rows past their expiry. Optional — the read
    path already filters by `is_valid`. Returns the number deleted."""
    cur = conn.execute(
        "DELETE FROM sessions WHERE expires_ts < ?",
        (time.time(),),
    )
    conn.commit()
    return int(cur.rowcount)
