"""Auth service unit tests (no FastAPI)."""

from __future__ import annotations

import time

import pytest

from shared.services.auth import (
    AccountLockedError,
    RateLimitConfig,
    UserExistsError,
    authenticate,
    create_session,
    create_user,
    get_session,
    get_user_by_email,
    hash_password,
    list_users,
    revoke_all_sessions,
    revoke_session,
    verify_password,
)


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "auth.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


def _rl(threshold: int = 5, window: int = 60, duration: int = 300) -> RateLimitConfig:
    return RateLimitConfig(
        threshold=threshold, window_seconds=window, duration_seconds=duration
    )


def test_hash_and_verify_password_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


async def test_create_user_and_lookup(db_conn) -> None:
    u = await create_user(db_conn, "alice@example.com", "p@ssword123")
    assert u.email == "alice@example.com"
    fetched = await get_user_by_email(db_conn, "ALICE@EXAMPLE.COM")
    assert fetched is not None
    assert fetched.id == u.id


async def test_duplicate_email_raises(db_conn) -> None:
    await create_user(db_conn, "a@b.com", "secret123")
    with pytest.raises(UserExistsError):
        await create_user(db_conn, "a@b.com", "another1234")


async def test_authenticate_success(db_conn) -> None:
    await create_user(db_conn, "a@b.com", "secret123")
    user = await authenticate(db_conn, "a@b.com", "secret123", "127.0.0.1", _rl())
    assert user is not None
    # last_login_ts populated
    fetched = await get_user_by_email(db_conn, "a@b.com")
    assert fetched is not None
    assert fetched.last_login_ts is not None


async def test_authenticate_wrong_password_returns_none(db_conn) -> None:
    await create_user(db_conn, "a@b.com", "secret123")
    user = await authenticate(db_conn, "a@b.com", "WRONG", "127.0.0.1", _rl())
    assert user is None


async def test_authenticate_unknown_email_returns_none(db_conn) -> None:
    user = await authenticate(
        db_conn, "ghost@example.com", "anything", "127.0.0.1", _rl()
    )
    assert user is None


async def test_lockout_after_threshold(db_conn) -> None:
    await create_user(db_conn, "a@b.com", "secret123")
    rl = _rl(threshold=3, window=60, duration=300)
    for _ in range(3):
        result = await authenticate(db_conn, "a@b.com", "WRONG", "127.0.0.1", rl)
        assert result is None
    with pytest.raises(AccountLockedError) as exc:
        await authenticate(db_conn, "a@b.com", "secret123", "127.0.0.1", rl)
    assert exc.value.retry_after_s > 0


async def test_lockout_window_expires(db_conn) -> None:
    """If failures fall outside the sliding window, lockout lifts."""
    await create_user(db_conn, "a@b.com", "secret123")
    rl = _rl(threshold=2, window=1, duration=2)
    for _ in range(2):
        await authenticate(db_conn, "a@b.com", "WRONG", "127.0.0.1", rl)
    # Wait for window to elapse
    time.sleep(1.5)
    user = await authenticate(db_conn, "a@b.com", "secret123", "127.0.0.1", rl)
    assert user is not None


async def test_session_create_and_get(db_conn) -> None:
    user = await create_user(db_conn, "a@b.com", "secret123")
    session = await create_session(
        db_conn, user, duration_seconds=3600, user_agent="ua", ip_address="1.1.1.1"
    )
    assert session.is_valid
    fetched = await get_session(db_conn, session.id)
    assert fetched is not None
    assert fetched.user_id == user.id


async def test_session_revoked_returns_none(db_conn) -> None:
    user = await create_user(db_conn, "a@b.com", "secret123")
    session = await create_session(
        db_conn, user, duration_seconds=3600
    )
    await revoke_session(db_conn, session.id)
    assert await get_session(db_conn, session.id) is None


async def test_revoke_all_sessions(db_conn) -> None:
    user = await create_user(db_conn, "a@b.com", "secret123")
    s1 = await create_session(db_conn, user, duration_seconds=3600)
    s2 = await create_session(db_conn, user, duration_seconds=3600)
    n = await revoke_all_sessions(db_conn, user.id)
    assert n == 2
    assert await get_session(db_conn, s1.id) is None
    assert await get_session(db_conn, s2.id) is None


async def test_list_users(db_conn) -> None:
    await create_user(db_conn, "a@b.com", "secret123")
    await create_user(db_conn, "c@d.com", "secret456")
    users = await list_users(db_conn)
    assert len(users) == 2
