"""FastAPI middleware: session auth + request logging.

Login rate-limiting lives inside the auth router (it needs the email
from the request body), not here. Public paths bypass auth entirely.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from shared.config import settings
from shared.db import get_connection
from shared.events import emit
from shared.services.auth import get_session

# Endpoints that bypass auth entirely.
PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/api/auth/login",
        "/api/auth/logout",  # Idempotent — handler clears cookie even when none.
        "/api/health",
        "/api/ready",
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
    }
)
PUBLIC_PREFIXES: tuple[str, ...] = ("/api/docs",)


def _is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return True
    # Non-/api paths fall through (Phase 7 frontend handles them).
    return not path.startswith("/api")


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """Validate session cookie on every protected /api/* request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if _is_public(path):
            return await call_next(request)

        cookie_name = settings.SESSION_COOKIE_NAME
        session_id = request.cookies.get(cookie_name)
        if not session_id:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401
            )

        conn = get_connection()
        try:
            session = await get_session(conn, session_id)
        finally:
            conn.close()
        if session is None:
            return JSONResponse(
                {"detail": "Session expired or invalid"}, status_code=401
            )

        # Stash on request.state so loggers / handlers can read it.
        request.state.session_id = session_id
        request.state.user_id = session.user_id
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Emit one event per /api/* request with method, path, status, duration."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if not path.startswith("/api"):
            return await call_next(request)

        start = time.time()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            elapsed_ms = int((time.time() - start) * 1000)
            user_id = getattr(request.state, "user_id", None)
            emit(
                "api",
                "info",
                "api_request",
                {
                    "method": request.method,
                    "path": path,
                    "status": response.status_code if response is not None else 500,
                    "elapsed_ms": elapsed_ms,
                    "user_id": user_id,
                    "ip": request.client.host if request.client else None,
                },
            )
