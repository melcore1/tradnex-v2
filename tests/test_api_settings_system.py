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


# ---- Phase 7: trading_mode + override_reasons ----


async def test_status_includes_trading_mode_paper(client_setup) -> None:
    """Phase 7 hard-codes trading_mode='paper' until Phase 8."""
    _, client = client_setup
    body = client.get("/api/system/status").json()
    assert body["trading_mode"] == "paper"


async def test_status_override_reasons_all_null_when_no_override(
    client_setup,
) -> None:
    _, client = client_setup
    body = client.get("/api/system/status").json()
    assert body["override_reasons"] == {
        "scanner": None,
        "monitor": None,
        "llm": None,
    }


async def test_monitor_paused_with_open_positions_emits_override(
    client_setup,
) -> None:
    """monitor_paused=True + at least one open position → override_reasons.monitor
    contains the human-readable explanation."""
    import time as _t

    conn, client = client_setup
    # Pause monitor
    client.post(
        "/api/system/toggle",
        json={"name": "monitor_paused", "enabled": False},  # enabled=false → paused
    )
    # Insert two open positions to verify the count + plural rendering
    for sym in ("NVDA250620C150", "MSFT250620C400"):
        conn.execute(
            "INSERT INTO positions (ticker, contract_symbol, side, quantity, "
            "entry_price, entry_ts, status) VALUES "
            "(?, ?, 'long', 1, 5.0, ?, 'open')",
            (sym.split("2")[0], sym, _t.time() - 3600),
        )
    conn.commit()
    body = client.get("/api/system/status").json()
    assert body["monitor_paused"] is True
    assert body["open_positions"] == 2
    assert body["override_reasons"]["monitor"] == (
        "Monitor forced active — 2 open positions"
    )
    assert body["override_reasons"]["scanner"] is None
    assert body["override_reasons"]["llm"] is None


async def test_monitor_paused_singular_position_uses_singular_word(
    client_setup,
) -> None:
    import time as _t

    conn, client = client_setup
    client.post(
        "/api/system/toggle",
        json={"name": "monitor_paused", "enabled": False},
    )
    conn.execute(
        "INSERT INTO positions (ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts, status) VALUES "
        "('NVDA', 'NVDA250620C150', 'long', 1, 5.0, ?, 'open')",
        (_t.time() - 3600,),
    )
    conn.commit()
    body = client.get("/api/system/status").json()
    assert body["override_reasons"]["monitor"] == (
        "Monitor forced active — 1 open position"
    )
