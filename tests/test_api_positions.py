"""/api/positions tests."""

from __future__ import annotations

import time

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


def _insert_open_position(conn, ticker: str = "NVDA") -> int:
    cur = conn.execute(
        "INSERT INTO positions (ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts, status) "
        "VALUES (?, 'NVDA250620C150', 'long', 1, 5.0, ?, 'open')",
        (ticker, time.time() - 3600),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


async def test_list_open_positions(client_setup) -> None:
    conn, client = client_setup
    pid = _insert_open_position(conn)
    r = client.get("/api/positions")
    assert r.status_code == 200
    body = r.json()
    assert any(p["id"] == pid for p in body)


async def test_get_position_detail(client_setup) -> None:
    conn, client = client_setup
    pid = _insert_open_position(conn)
    r = client.get(f"/api/positions/{pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["position"]["id"] == pid
    assert "lifecycle_events" in body


async def test_get_missing_position_404(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/positions/99999")
    assert r.status_code == 404


async def test_lifecycle_endpoint(client_setup) -> None:
    conn, client = client_setup
    pid = _insert_open_position(conn)
    # Insert a lifecycle event manually
    conn.execute(
        "INSERT INTO position_lifecycle_events "
        "(position_id, event_type, cycle_id, payload_json, timestamp) "
        "VALUES (?, 'opened', NULL, '{}', ?)",
        (pid, time.time()),
    )
    conn.commit()
    r = client.get(f"/api/positions/{pid}/lifecycle")
    assert r.status_code == 200
    events = r.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "opened"
