"""Schwab OAuth token refresh.

Phase 8a.5: Schwab access tokens expire every 30 min; refresh tokens every
7 days on a rolling window (any successful refresh resets it). The data
service runs `refresh_schwab_token` every 25 min via apscheduler; the API
exposes a manual trigger at `POST /api/schwab/oauth/refresh`.

The refresh exchanges `{grant_type=refresh_token, refresh_token=...}` against
Schwab's token endpoint with HTTP Basic auth from the `schwab_client`
credential row. Schwab MAY rotate the refresh token on each refresh; when
rotation happens, we reset `refresh_token_expires_at` to `now + 7d`.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel

from shared.events import emit
from shared.services.credentials import (
    get_credential_record,
    get_credential_secrets,
    upsert_credential,
)
from shared.services.encryption import EncryptionService

SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
SCHWAB_AUTHORIZE_URL = "https://api.schwabapi.com/v1/oauth/authorize"
ACCESS_TOKEN_LIFETIME_SECONDS_DEFAULT = 1800  # Schwab's documented 30 min
REFRESH_TOKEN_LIFETIME_DAYS = 7


class RefreshResult(BaseModel):
    """Outcome of a Schwab refresh attempt."""

    success: bool
    expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    refresh_token_rotated: bool = False
    message: str


async def refresh_schwab_token(
    conn: sqlite3.Connection,
    encryption: EncryptionService,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> RefreshResult:
    """Exchange the stored refresh_token for a new access_token.

    Returns `RefreshResult(success=False, ...)` when no credentials exist,
    or when Schwab returns a non-2xx response. Successful refresh updates
    the `schwab_oauth` row and emits `token_refreshed`.

    Args:
        conn: Open SQLite connection.
        encryption: EncryptionService bound to the master key.
        http_client: Optional pre-built httpx.AsyncClient (tests inject a
            transport-mocked client). When None, opens a short-lived client.
    """
    oauth_secrets = get_credential_secrets(
        conn, encryption, "schwab_oauth", use_cache=False
    )
    if not oauth_secrets or not oauth_secrets.get("refresh_token"):
        return RefreshResult(
            success=False, message="No Schwab OAuth credentials configured"
        )

    client_secrets = get_credential_secrets(
        conn, encryption, "schwab_client", use_cache=False
    )
    if not client_secrets:
        return RefreshResult(
            success=False,
            message="Schwab Client ID/Secret not configured (schwab_client)",
        )

    client_id = client_secrets.get("client_id")
    client_secret = client_secrets.get("client_secret")
    if not client_id or not client_secret:
        return RefreshResult(
            success=False,
            message="Schwab client credentials missing client_id/client_secret",
        )

    owns_client = http_client is None
    http = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await http.post(
            SCHWAB_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": oauth_secrets["refresh_token"],
            },
            auth=(client_id, client_secret),
        )
    except httpx.HTTPError as exc:
        emit(
            "schwab_oauth",
            "error",
            "refresh_transport_failed",
            {"error": str(exc)[:300]},
        )
        return RefreshResult(
            success=False, message=f"Transport error: {exc}"
        )
    finally:
        if owns_client:
            await http.aclose()

    if response.status_code != 200:
        emit(
            "schwab_oauth",
            "error",
            "refresh_failed",
            {
                "status": response.status_code,
                "body": response.text[:500],
            },
        )
        return RefreshResult(
            success=False,
            message=(
                f"Schwab refresh returned {response.status_code}. "
                "Re-authentication may be required."
            ),
        )

    payload: dict[str, Any] = response.json()
    new_access = payload.get("access_token")
    new_refresh = payload.get("refresh_token") or oauth_secrets["refresh_token"]
    if not new_access:
        emit(
            "schwab_oauth",
            "error",
            "refresh_missing_access_token",
            {"keys": sorted(payload.keys())},
        )
        return RefreshResult(
            success=False,
            message="Schwab refresh response missing access_token",
        )

    expires_in = int(payload.get("expires_in", ACCESS_TOKEN_LIFETIME_SECONDS_DEFAULT))
    now = datetime.now(UTC)
    new_access_expires = now + timedelta(seconds=expires_in)

    refresh_rotated = new_refresh != oauth_secrets["refresh_token"]
    if refresh_rotated:
        new_refresh_expires: datetime | None = now + timedelta(
            days=REFRESH_TOKEN_LIFETIME_DAYS
        )
    else:
        existing_record = get_credential_record(conn, "schwab_oauth")
        new_refresh_expires = (
            existing_record.refresh_token_expires_at
            if existing_record is not None
            else now + timedelta(days=REFRESH_TOKEN_LIFETIME_DAYS)
        )

    upsert_credential(
        conn,
        encryption,
        "schwab_oauth",
        secrets={
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": payload.get("token_type", "Bearer"),
            "scope": payload.get("scope", ""),
        },
        expires_at=new_access_expires,
        refresh_token_expires_at=new_refresh_expires,
        notes=oauth_secrets.get("notes"),
    )

    emit(
        "schwab_oauth",
        "info",
        "token_refreshed",
        {
            "expires_at": new_access_expires.isoformat(),
            "refresh_token_rotated": refresh_rotated,
        },
    )

    return RefreshResult(
        success=True,
        expires_at=new_access_expires,
        refresh_token_expires_at=new_refresh_expires,
        refresh_token_rotated=refresh_rotated,
        message="Token refreshed successfully",
    )
