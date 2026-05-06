"""FastAPI auth flow tests (login / logout / me / lockout)."""

from __future__ import annotations

import pytest

from tests._api_helpers import build_test_client, reset_modules_for_test_db, seed_user


@pytest.fixture
async def auth_setup(tmp_path, monkeypatch):
    conn = reset_modules_for_test_db(tmp_path, monkeypatch)
    user = await seed_user(conn)
    client = build_test_client()
    yield conn, client, user
    conn.close()


async def test_login_success_sets_cookie(auth_setup) -> None:
    _conn, client, _user = auth_setup
    resp = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpass1234"},
    )
    assert resp.status_code == 200
    assert "tradnex_session" in client.cookies
    body = resp.json()
    assert body["user"] == "test@example.com"


async def test_login_wrong_password_returns_401(auth_setup) -> None:
    _, client, _ = auth_setup
    resp = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "wrongwrongwrong"},
    )
    assert resp.status_code == 401
    assert "Invalid" in resp.json()["detail"]


async def test_login_unknown_email_returns_401(auth_setup) -> None:
    """Same response shape as wrong-password — no enumeration."""
    _, client, _ = auth_setup
    resp = client.post(
        "/api/auth/login",
        json={"email": "ghost@nowhere.com", "password": "anything12345"},
    )
    assert resp.status_code == 401


async def test_lockout_after_threshold_failures(auth_setup) -> None:
    """Force a low threshold via dependency override; 3 fails → 4th blocked
    with 429."""
    _, client, _ = auth_setup
    from services.api.deps import get_rate_limit_config
    from services.api.main import app
    from shared.services.auth import RateLimitConfig

    app.dependency_overrides[get_rate_limit_config] = lambda: RateLimitConfig(
        threshold=3, window_seconds=60, duration_seconds=3600
    )
    try:
        for _ in range(3):
            r = client.post(
                "/api/auth/login",
                json={"email": "test@example.com", "password": "WRONG_____"},
            )
            assert r.status_code == 401
        r = client.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "testpass1234"},
        )
        assert r.status_code == 429
        assert "locked" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


async def test_logout_revokes_session(auth_setup) -> None:
    _, client, _ = auth_setup
    client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpass1234"},
    )
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 401


async def test_me_requires_session(auth_setup) -> None:
    _, client, _ = auth_setup
    r = client.get("/api/auth/me")
    assert r.status_code == 401


async def test_me_returns_user_when_authed(auth_setup) -> None:
    _, client, _ = auth_setup
    client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpass1234"},
    )
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "test@example.com"


async def test_logout_idempotent_without_cookie(auth_setup) -> None:
    _, client, _ = auth_setup
    r = client.post("/api/auth/logout")
    assert r.status_code == 200


async def test_health_does_not_require_auth(auth_setup) -> None:
    _, client, _ = auth_setup
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_docs_does_not_require_auth(auth_setup) -> None:
    _, client, _ = auth_setup
    r = client.get("/api/docs")
    assert r.status_code == 200


async def test_openapi_does_not_require_auth(auth_setup) -> None:
    _, client, _ = auth_setup
    r = client.get("/api/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["info"]["title"] == "TradNex 2 API"
