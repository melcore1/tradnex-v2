"""SessionAuthMiddleware tests — public path bypass + protected path enforcement."""

from __future__ import annotations

import pytest

from tests._api_helpers import build_test_client, reset_modules_for_test_db, seed_user


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    conn = reset_modules_for_test_db(tmp_path, monkeypatch)
    await seed_user(conn)
    client = build_test_client()
    yield conn, client
    conn.close()


async def test_public_health_no_auth(setup) -> None:
    _, client = setup
    assert client.get("/api/health").status_code == 200


async def test_public_login_no_auth(setup) -> None:
    _, client = setup
    # Failed login still returns 401 from the handler, NOT from middleware.
    r = client.post(
        "/api/auth/login",
        json={"email": "nope@nope.com", "password": "nope12345"},
    )
    assert r.status_code == 401  # auth handler, not middleware


async def test_protected_endpoint_requires_session(setup) -> None:
    _, client = setup
    r = client.get("/api/candidates")
    assert r.status_code == 401


async def test_protected_endpoint_after_login(setup) -> None:
    _, client = setup
    client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpass1234"},
    )
    r = client.get("/api/candidates")
    assert r.status_code == 200


async def test_revoked_session_rejected(setup) -> None:
    conn, client = setup
    client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpass1234"},
    )
    # Revoke directly in DB
    conn.execute("UPDATE sessions SET revoked = 1")
    conn.commit()
    r = client.get("/api/candidates")
    assert r.status_code == 401


async def test_openapi_public(setup) -> None:
    _, client = setup
    r = client.get("/api/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    # Confirm a known endpoint is in the schema
    assert "/api/candidates" in spec["paths"]
