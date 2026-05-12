"""/api/schwab/oauth — Schwab Trader API OAuth flow.

Phase 8a.5. Replaces the disk-based `scripts/schwab_auth.py` bootstrap with
an in-app, CSRF-protected OAuth Authorization Code flow. Tokens land in the
encrypted `credentials` store (`schwab_oauth`); Client ID/Secret are read
from `schwab_client` (configured by the user via Settings → Credentials).

Endpoints
---------
GET    /api/schwab/oauth/auth/start   redirect to Schwab authorize URL
GET    /api/schwab/oauth/callback     exchange ?code for tokens, persist
POST   /api/schwab/oauth/refresh      manual refresh trigger (auto-refresh
                                       runs every 25 min in services/data)
DELETE /api/schwab/oauth/disconnect   remove the schwab_oauth credential
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from services.api.deps import DB, CurrentUser, Encryption
from services.api.oauth_state import (
    OAuthStateInvalid,
    make_state_token,
    verify_state_token,
)
from shared.events import emit
from shared.services.credentials import (
    delete_credential,
    get_credential_secrets,
    upsert_credential,
)
from shared.services.schwab_refresh import (
    REFRESH_TOKEN_LIFETIME_DAYS,
    SCHWAB_AUTHORIZE_URL,
    SCHWAB_TOKEN_URL,
    RefreshResult,
    refresh_schwab_token,
)

router = APIRouter()


class RefreshResponse(BaseModel):
    """Manual-refresh API response."""

    success: bool
    expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    refresh_token_rotated: bool = False
    message: str


def _redirect_uri() -> str:
    # Read lazily so test fixtures that reload config pick up the change.
    from shared import config as _config

    return _config.settings.SCHWAB_REDIRECT_URI


def _oauth_enabled() -> bool:
    from shared import config as _config

    return bool(_config.settings.SCHWAB_OAUTH_ENABLED)


def _require_oauth_enabled() -> None:
    if not _oauth_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Schwab OAuth is disabled (SCHWAB_OAUTH_ENABLED=false)",
        )


async def get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Yield a short-lived httpx.AsyncClient. Test fixtures override via
    `app.dependency_overrides[get_http_client]`."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        yield client


HttpClient = Annotated[httpx.AsyncClient, Depends(get_http_client)]


@router.get("/auth/start")
async def auth_start(
    user: CurrentUser,
    db: DB,
    encryption: Encryption,
) -> RedirectResponse:
    """Start the Schwab OAuth flow.

    Reads the user's `schwab_client` (Client ID/Secret) from the encrypted
    store and redirects the browser to Schwab's authorize URL with a
    Fernet-signed state token.
    """
    _require_oauth_enabled()

    client_secrets = get_credential_secrets(db, encryption, "schwab_client")
    if not client_secrets or not client_secrets.get("client_id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Schwab Client ID not configured. Add via "
                "Settings → Credentials before connecting."
            ),
        )

    state = make_state_token(user_id=user.id, encryption=encryption)
    params = {
        "client_id": client_secrets["client_id"],
        "redirect_uri": _redirect_uri(),
        "state": state,
        "response_type": "code",
    }
    url = f"{SCHWAB_AUTHORIZE_URL}?{urlencode(params)}"
    emit("schwab_oauth", "info", "oauth_started", {"user_id": user.id})
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/callback")
async def callback(
    user: CurrentUser,
    db: DB,
    encryption: Encryption,
    http: HttpClient,
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
) -> RedirectResponse:
    """Receive Schwab's authorization code, exchange for tokens, persist.

    On success, redirects to `/settings/credentials?schwab=connected` so
    the UI can show a toast and re-render the card.
    """
    _require_oauth_enabled()

    try:
        verify_state_token(state, expected_user_id=user.id, encryption=encryption)
    except OAuthStateInvalid as exc:
        emit(
            "schwab_oauth",
            "warn",
            "callback_state_invalid",
            {"error": str(exc)[:200], "user_id": user.id},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth state verification failed: {exc}",
        ) from exc

    client_secrets = get_credential_secrets(db, encryption, "schwab_client")
    if not client_secrets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Schwab client credentials missing — re-enter and retry.",
        )

    try:
        response = await http.post(
            SCHWAB_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _redirect_uri(),
            },
            auth=(client_secrets["client_id"], client_secrets["client_secret"]),
        )
    except httpx.HTTPError as exc:
        emit(
            "schwab_oauth",
            "error",
            "token_exchange_transport_failed",
            {"error": str(exc)[:300]},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Schwab token exchange transport error: {exc}",
        ) from exc

    if response.status_code != 200:
        emit(
            "schwab_oauth",
            "error",
            "token_exchange_failed",
            {
                "status": response.status_code,
                "body": response.text[:500],
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Schwab token exchange failed: {response.status_code}",
        )

    payload: dict[str, Any] = response.json()
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not access_token or not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Schwab response missing access_token or refresh_token",
        )

    expires_in = int(payload.get("expires_in", 1800))
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=expires_in)
    refresh_expires_at = now + timedelta(days=REFRESH_TOKEN_LIFETIME_DAYS)

    upsert_credential(
        db,
        encryption,
        "schwab_oauth",
        secrets={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": payload.get("token_type", "Bearer"),
            "scope": payload.get("scope", ""),
        },
        expires_at=expires_at,
        refresh_token_expires_at=refresh_expires_at,
        notes=f"OAuth completed by user_id={user.id}",
        user_id=user.id,
    )

    emit(
        "schwab_oauth",
        "info",
        "oauth_completed",
        {"user_id": user.id, "expires_at": expires_at.isoformat()},
    )
    return RedirectResponse(
        url="/settings/credentials?schwab=connected",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    user: CurrentUser,
    db: DB,
    encryption: Encryption,
    http: HttpClient,
) -> RefreshResponse:
    """Manually trigger a token refresh.

    The auto-refresh task in `services/data` runs every 25 min; this is
    for the "Refresh now" button on the Credentials page.
    """
    _require_oauth_enabled()
    result: RefreshResult = await refresh_schwab_token(db, encryption, http_client=http)
    if not result.success:
        # The helper has already emitted the error event. Surface a 502 so
        # the UI knows to show a banner.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.message,
        )
    return RefreshResponse(
        success=result.success,
        expires_at=result.expires_at,
        refresh_token_expires_at=result.refresh_token_expires_at,
        refresh_token_rotated=result.refresh_token_rotated,
        message=result.message,
    )


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    user: CurrentUser,
    db: DB,
    _: Encryption,
) -> None:
    """Remove the `schwab_oauth` credential. `schwab_client` is preserved
    so reconnecting only requires another OAuth handshake.
    """
    deleted = delete_credential(db, "schwab_oauth", user_id=user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Schwab OAuth credential to disconnect",
        )
    emit(
        "schwab_oauth",
        "info",
        "oauth_disconnected",
        {"user_id": user.id},
    )


