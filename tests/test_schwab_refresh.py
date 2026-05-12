"""Tests for shared.services.schwab_refresh."""

from __future__ import annotations

import importlib
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from shared.services.credentials import (
    clear_cache,
    get_credential_record,
    upsert_credential,
)
from shared.services.schwab_refresh import (
    SCHWAB_TOKEN_URL,
    RefreshResult,
    refresh_schwab_token,
)
from tests._credential_helpers import TEST_ENCRYPTION_KEY, get_test_encryption


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "refresh.db"))
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    from shared import config as cfg
    from shared import db as db_mod

    importlib.reload(cfg)
    importlib.reload(db_mod)
    db_mod.run_migrations()
    clear_cache()
    c = db_mod.get_connection()
    yield c
    c.close()


def _seed_client_creds(conn: sqlite3.Connection) -> None:
    upsert_credential(
        conn,
        get_test_encryption(),
        "schwab_client",
        secrets={"client_id": "cid", "client_secret": "csecret"},
    )


def _seed_oauth_tokens(
    conn: sqlite3.Connection,
    *,
    refresh_token: str = "rt_v1",
    refresh_expires_at: datetime | None = None,
) -> None:
    enc = get_test_encryption()
    upsert_credential(
        conn,
        enc,
        "schwab_oauth",
        secrets={
            "access_token": "at_v1",
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "scope": "",
        },
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        refresh_token_expires_at=refresh_expires_at
        or (datetime.now(UTC) + timedelta(days=6)),
    )


def _mock_http(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_refresh_no_oauth_credentials(conn) -> None:
    enc = get_test_encryption()
    result = await refresh_schwab_token(conn, enc)
    assert result == RefreshResult(
        success=False, message="No Schwab OAuth credentials configured"
    )


async def test_refresh_no_client_credentials(conn) -> None:
    _seed_oauth_tokens(conn)
    enc = get_test_encryption()
    result = await refresh_schwab_token(conn, enc)
    assert result.success is False
    assert "schwab_client" in result.message


async def test_refresh_success_without_rotation(conn) -> None:
    _seed_client_creds(conn)
    refresh_expires_at = datetime.now(UTC) + timedelta(days=6)
    _seed_oauth_tokens(conn, refresh_expires_at=refresh_expires_at)

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == SCHWAB_TOKEN_URL
        assert request.method == "POST"
        captured["body"] = request.content.decode()
        captured["auth_header"] = request.headers.get("authorization", "")
        return httpx.Response(
            200,
            json={
                "access_token": "at_v2",
                "refresh_token": "rt_v1",  # unchanged → no rotation
                "expires_in": 1800,
                "token_type": "Bearer",
                "scope": "trading",
            },
        )

    async with _mock_http(handler) as http:
        result = await refresh_schwab_token(
            conn, get_test_encryption(), http_client=http
        )

    assert result.success is True
    assert result.refresh_token_rotated is False
    assert "grant_type=refresh_token" in captured["body"]
    assert "refresh_token=rt_v1" in captured["body"]
    assert captured["auth_header"].startswith("Basic ")

    # New refresh_token_expires_at must NOT have moved (rolling preserved).
    record = get_credential_record(conn, "schwab_oauth")
    assert record is not None
    assert record.refresh_token_expires_at is not None
    delta = abs(
        (record.refresh_token_expires_at - refresh_expires_at).total_seconds()
    )
    assert delta < 1.0


async def test_refresh_rotated_resets_expiration(conn) -> None:
    _seed_client_creds(conn)
    refresh_expires_at = datetime.now(UTC) + timedelta(days=2)
    _seed_oauth_tokens(conn, refresh_expires_at=refresh_expires_at)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "at_v2",
                "refresh_token": "rt_v2",  # rotated
                "expires_in": 1800,
            },
        )

    async with _mock_http(handler) as http:
        result = await refresh_schwab_token(
            conn, get_test_encryption(), http_client=http
        )

    assert result.success is True
    assert result.refresh_token_rotated is True
    # New refresh window is now+7d, not the old +2d.
    assert result.refresh_token_expires_at is not None
    assert result.refresh_token_expires_at > refresh_expires_at + timedelta(days=3)


async def test_refresh_4xx_emits_and_returns_failure(conn) -> None:
    _seed_client_creds(conn)
    _seed_oauth_tokens(conn)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": "invalid_grant"}
        )

    async with _mock_http(handler) as http:
        result = await refresh_schwab_token(
            conn, get_test_encryption(), http_client=http
        )
    assert result.success is False
    assert "401" in result.message
    event_row = conn.execute(
        "SELECT event_type FROM events WHERE event_type='refresh_failed'"
    ).fetchone()
    assert event_row is not None


async def test_refresh_updates_db_row(conn) -> None:
    _seed_client_creds(conn)
    _seed_oauth_tokens(conn)
    enc = get_test_encryption()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "rotated_access",
                "refresh_token": "rotated_refresh",
                "expires_in": 1800,
            },
        )

    async with _mock_http(handler) as http:
        await refresh_schwab_token(conn, enc, http_client=http)

    from shared.services.credentials import get_credential_secrets

    secrets = get_credential_secrets(conn, enc, "schwab_oauth", use_cache=False)
    assert secrets is not None
    assert secrets["access_token"] == "rotated_access"
    assert secrets["refresh_token"] == "rotated_refresh"


async def test_refresh_emits_token_refreshed_event(conn) -> None:
    _seed_client_creds(conn)
    _seed_oauth_tokens(conn)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "a", "refresh_token": "rt_v1", "expires_in": 1800},
        )

    async with _mock_http(handler) as http:
        await refresh_schwab_token(
            conn, get_test_encryption(), http_client=http
        )

    row = conn.execute(
        "SELECT payload FROM events WHERE event_type='token_refreshed' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
