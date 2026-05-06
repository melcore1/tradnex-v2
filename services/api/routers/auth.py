"""Auth endpoints: /api/auth/login, /api/auth/logout, /api/auth/me."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status

from services.api.deps import DB, CurrentUser, RateLimit
from services.api.schemas import LoginRequest, LoginResponse, MeResponse
from shared.config import settings
from shared.events import emit
from shared.services.auth import (
    AccountLockedError,
    authenticate,
    create_session,
    revoke_session,
)

router = APIRouter()


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DB,
    rate_limit: RateLimit,
) -> LoginResponse:
    """Authenticate by email + password, set the session cookie."""
    ip = request.client.host if request.client else None
    try:
        user = await authenticate(
            db, payload.email, payload.password, ip, rate_limit
        )
    except AccountLockedError as e:
        emit(
            "api",
            "warn",
            "login_locked",
            {"email": payload.email, "retry_after_s": e.retry_after_s, "ip": ip},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account temporarily locked. Retry in {e.retry_after_s}s.",
            headers={"Retry-After": str(e.retry_after_s)},
        ) from e

    if user is None:
        # Same response shape for invalid email AND wrong password.
        emit("api", "warn", "login_failed", {"email": payload.email, "ip": ip})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    duration_s = settings.SESSION_DURATION_DAYS * 24 * 60 * 60
    session = await create_session(
        db,
        user,
        duration_seconds=duration_s,
        user_agent=request.headers.get("User-Agent"),
        ip_address=ip,
    )

    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=session.id,
        max_age=duration_s,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )
    emit(
        "api",
        "info",
        "login_success",
        {"user_id": user.id, "email": user.email, "ip": ip},
    )
    return LoginResponse(
        user=user.email,
        expires_at=datetime.now(UTC) + timedelta(seconds=duration_s),
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: DB,
) -> dict[str, str]:
    """Revoke the current session and clear the cookie. Idempotent: a
    request without a cookie still succeeds with status='ok'."""
    sid = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if sid:
        await revoke_session(db, sid)
        emit(
            "api",
            "info",
            "logout",
            {"user_id": getattr(request.state, "user_id", None)},
        )
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"status": "ok"}


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser) -> MeResponse:
    """Return the logged-in user's identity."""
    return MeResponse(
        id=user.id,
        email=user.email,
        last_login_ts=user.last_login_ts,
    )
