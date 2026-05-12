"""Tests for /api/system/data-status."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

import pytest

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
    yield conn, client, monkeypatch
    conn.close()


async def test_data_status_mock_client(setup) -> None:
    _, client, _ = setup
    r = client.get("/api/system/data-status")
    assert r.status_code == 200
    body = r.json()
    assert body["active_client"] == "mock"
    assert body["is_configured"] is True
    assert body["schwab_token_status"] is None


async def test_data_status_schwab_unconfigured(setup) -> None:
    _, client, monkeypatch = setup
    monkeypatch.setenv("DATA_CLIENT", "schwab")
    from shared import config as cfg

    importlib.reload(cfg)
    r = client.get("/api/system/data-status")
    assert r.status_code == 200
    body = r.json()
    assert body["active_client"] == "schwab"
    assert body["is_configured"] is False
    assert body["schwab_token_status"] is None


async def test_data_status_schwab_connected(setup) -> None:
    conn, client, monkeypatch = setup
    monkeypatch.setenv("DATA_CLIENT", "schwab")
    from shared import config as cfg

    importlib.reload(cfg)

    enc = get_test_encryption()
    upsert_credential(
        conn,
        enc,
        "schwab_client",
        secrets={"client_id": "cid", "client_secret": "csec"},
    )
    refresh_expires = datetime.now(UTC) + timedelta(days=5)
    upsert_credential(
        conn,
        enc,
        "schwab_oauth",
        secrets={"access_token": "at", "refresh_token": "rt"},
        expires_at=datetime.now(UTC) + timedelta(minutes=27),
        refresh_token_expires_at=refresh_expires,
    )

    r = client.get("/api/system/data-status")
    assert r.status_code == 200
    body = r.json()
    assert body["active_client"] == "schwab"
    assert body["is_configured"] is True
    status = body["schwab_token_status"]
    assert status is not None
    assert status["refresh_token_hours_remaining"] is not None
    # ~5 days × 24h = ~120h (allow 1h slack for test timing)
    assert 118 < status["refresh_token_hours_remaining"] < 121
