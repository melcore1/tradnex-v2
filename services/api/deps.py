"""FastAPI dependency-injection helpers.

`get_db` yields a fresh SQLite connection per request; `get_current_user`
validates the session cookie and returns the User. `get_rate_limit_config`
exposes the global config so test fixtures can override.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status

from shared.config import settings
from shared.db import get_connection
from shared.services.auth import (
    RateLimitConfig,
    User,
    get_session,
    get_user_by_id,
)


def get_db() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


DB = Annotated[sqlite3.Connection, Depends(get_db)]


def get_rate_limit_config() -> RateLimitConfig:
    return RateLimitConfig(
        threshold=settings.LOGIN_LOCKOUT_THRESHOLD,
        window_seconds=settings.LOGIN_LOCKOUT_WINDOW_SECONDS,
        duration_seconds=settings.LOGIN_LOCKOUT_DURATION_SECONDS,
    )


RateLimit = Annotated[RateLimitConfig, Depends(get_rate_limit_config)]


def get_session_id(
    request: Request,
) -> str | None:
    """Read the session cookie. Returns None when missing.
    Falls through any value type — middleware handles validation."""
    cookie_name = settings.SESSION_COOKIE_NAME
    return request.cookies.get(cookie_name)


async def get_current_user(
    request: Request,
    db: DB,
    session_id: Annotated[str | None, Depends(get_session_id)] = None,
    auth_cookie: Annotated[str | None, Cookie(alias="tradnex_session")] = None,
) -> User:
    """Resolve the current user from the session cookie.

    Path-operations that depend on this raise 401 when:
    - No cookie present
    - Session not found / expired / revoked
    - User row missing (deleted while logged in)

    The middleware also validates auth, but this dependency lets path
    operations access the User Pydantic model directly.
    """
    sid = session_id or auth_cookie
    if not sid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    session = await get_session(db, sid)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )
    user = await get_user_by_id(db, session.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    # Make the user available on request.state so middleware/loggers can pick it up
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
