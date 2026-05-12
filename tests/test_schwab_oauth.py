"""Tests for /api/schwab/oauth/* — auth/start, callback, refresh, disconnect."""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from services.api.oauth_state import make_state_token
from shared.services.credentials import clear_cache, upsert_credential
from tests._api_helpers import (
    build_test_client,
    reset_modules_for_test_db,
    seed_user,
)
from tests._credential_helpers import TEST_ENCRYPTION_KEY, get_test_encryption


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("SCHWAB_OAUTH_ENABLED", "true")
    monkeypatch.setenv(
        "SCHWAB_REDIRECT_URI",
        "https://test.example.com/api/schwab/oauth/callback",
    )
    conn = reset_modules_for_test_db(tmp_path, monkeypatch)
    from shared import config as cfg

    importlib.reload(cfg)
    clear_cache()

    await seed_user(conn)
    client = build_test_client()
    client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpass1234"},
    )
    yield conn, client
    conn.close()


def _seed_client_creds(conn) -> None:
    upsert_credential(
        conn,
        get_test_encryption(),
        "schwab_client",
        secrets={"client_id": "cid_test", "client_secret": "csecret_test"},
    )


def _override_http(client_app, handler) -> None:
    """Inject a MockTransport-backed AsyncClient via dependency override."""
    from services.api.routers.schwab_oauth import get_http_client

    async def _factory() -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c

    client_app.app.dependency_overrides[get_http_client] = _factory


async def test_auth_start_503_when_disabled(setup, monkeypatch) -> None:
    _, client = setup
    monkeypatch.setenv("SCHWAB_OAUTH_ENABLED", "false")
    from shared import config as cfg

    importlib.reload(cfg)
    r = client.get("/api/schwab/oauth/auth/start", follow_redirects=False)
    assert r.status_code == 503


async def test_auth_start_400_when_no_client_creds(setup) -> None:
    _, client = setup
    r = client.get("/api/schwab/oauth/auth/start", follow_redirects=False)
    assert r.status_code == 400
    assert "Client ID" in r.json()["detail"]


async def test_auth_start_redirects_to_schwab(setup) -> None:
    conn, client = setup
    _seed_client_creds(conn)
    r = client.get("/api/schwab/oauth/auth/start", follow_redirects=False)
    assert r.status_code == 307
    location = r.headers["location"]
    assert location.startswith("https://api.schwabapi.com/v1/oauth/authorize")
    assert "client_id=cid_test" in location
    assert "response_type=code" in location
    assert "state=" in location


async def test_callback_rejects_invalid_state(setup) -> None:
    conn, client = setup
    _seed_client_creds(conn)
    r = client.get(
        "/api/schwab/oauth/callback",
        params={"code": "auth_code_xyz", "state": "not-a-real-state"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "state" in r.json()["detail"].lower()


async def test_callback_exchanges_code_and_persists(setup) -> None:
    conn, client = setup
    _seed_client_creds(conn)
    enc = get_test_encryption()

    user_row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    user_id = user_row["id"]
    state = make_state_token(user_id=user_id, encryption=enc)

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "access_token": "new_access",
                "refresh_token": "new_refresh",
                "token_type": "Bearer",
                "scope": "trading",
                "expires_in": 1800,
            },
        )

    _override_http(client, handler)
    r = client.get(
        "/api/schwab/oauth/callback",
        params={"code": "auth_code_xyz", "state": state},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/settings/credentials?schwab=connected"
    assert "auth_code_xyz" in captured["body"]

    # schwab_oauth row exists with the new tokens (verify via decrypt)
    from shared.services.credentials import get_credential_secrets

    secrets = get_credential_secrets(conn, enc, "schwab_oauth", use_cache=False)
    assert secrets is not None
    assert secrets["access_token"] == "new_access"
    assert secrets["refresh_token"] == "new_refresh"


async def test_callback_502_on_schwab_4xx(setup) -> None:
    conn, client = setup
    _seed_client_creds(conn)
    enc = get_test_encryption()
    user_row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    state = make_state_token(user_id=user_row["id"], encryption=enc)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    _override_http(client, handler)
    r = client.get(
        "/api/schwab/oauth/callback",
        params={"code": "bad_code", "state": state},
        follow_redirects=False,
    )
    assert r.status_code == 502


async def test_refresh_endpoint_updates_db(setup) -> None:
    conn, client = setup
    _seed_client_creds(conn)
    enc = get_test_encryption()
    upsert_credential(
        conn,
        enc,
        "schwab_oauth",
        secrets={
            "access_token": "old_at",
            "refresh_token": "old_rt",
            "token_type": "Bearer",
            "scope": "",
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "refreshed_at",
                "refresh_token": "old_rt",
                "expires_in": 1800,
            },
        )

    _override_http(client, handler)
    r = client.post("/api/schwab/oauth/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["refresh_token_rotated"] is False

    from shared.services.credentials import get_credential_secrets

    secrets = get_credential_secrets(conn, enc, "schwab_oauth", use_cache=False)
    assert secrets is not None
    assert secrets["access_token"] == "refreshed_at"


async def test_disconnect_removes_row(setup) -> None:
    conn, client = setup
    _seed_client_creds(conn)
    upsert_credential(
        conn,
        get_test_encryption(),
        "schwab_oauth",
        secrets={"access_token": "a", "refresh_token": "r"},
    )
    r = client.delete("/api/schwab/oauth/disconnect")
    assert r.status_code == 204

    row = conn.execute(
        "SELECT 1 FROM credentials WHERE credential_type='schwab_oauth'"
    ).fetchone()
    assert row is None
    # schwab_client preserved
    row2 = conn.execute(
        "SELECT 1 FROM credentials WHERE credential_type='schwab_client'"
    ).fetchone()
    assert row2 is not None


async def test_disconnect_404_when_not_configured(setup) -> None:
    _, client = setup
    r = client.delete("/api/schwab/oauth/disconnect")
    assert r.status_code == 404
