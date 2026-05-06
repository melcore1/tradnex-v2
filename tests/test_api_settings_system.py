"""/api/settings + /api/system tests."""

from __future__ import annotations

import pytest

from tests._api_helpers import build_test_client, reset_modules_for_test_db, seed_user


@pytest.fixture
async def client_setup(tmp_path, monkeypatch):
    conn = reset_modules_for_test_db(tmp_path, monkeypatch)
    await seed_user(conn)
    client = build_test_client()
    client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpass1234"},
    )
    yield conn, client
    conn.close()


async def test_get_settings_returns_dict(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert "settings_json" in r.json()


async def test_patch_merges_keys(client_setup) -> None:
    _, client = client_setup
    r = client.patch(
        "/api/settings",
        json={"updates": {"foo": "bar", "nested": {"x": 1}}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["settings_json"]["foo"] == "bar"
    # second patch preserves earlier keys
    r2 = client.patch("/api/settings", json={"updates": {"baz": 2}})
    assert r2.json()["settings_json"]["foo"] == "bar"
    assert r2.json()["settings_json"]["baz"] == 2


async def test_system_status_aggregates(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/system/status")
    assert r.status_code == 200
    body = r.json()
    assert "paused" in body
    assert "monitor_paused" in body
    assert "llm_enabled" in body
    assert body["queue_depth"] >= 0
    assert body["open_positions"] >= 0


async def test_toggle_paused(client_setup) -> None:
    """enabled=false on `paused` means pause the scanner — stored value=true."""
    _, client = client_setup
    r = client.post("/api/system/toggle", json={"name": "paused", "enabled": False})
    assert r.status_code == 200
    assert r.json()["paused"] is True
    r2 = client.post("/api/system/toggle", json={"name": "paused", "enabled": True})
    assert r2.json()["paused"] is False


async def test_toggle_llm_enabled(client_setup) -> None:
    _, client = client_setup
    r = client.post(
        "/api/system/toggle",
        json={"name": "llm_enabled", "enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["llm_enabled"] is False


async def test_toggle_monitor_paused(client_setup) -> None:
    _, client = client_setup
    r = client.post(
        "/api/system/toggle",
        json={"name": "monitor_paused", "enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["monitor_paused"] is True


async def test_unknown_toggle_rejected(client_setup) -> None:
    _, client = client_setup
    r = client.post(
        "/api/system/toggle",
        json={"name": "rogue_flag", "enabled": True},
    )
    # Pydantic literal validation → 422
    assert r.status_code == 422
