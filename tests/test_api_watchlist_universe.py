"""/api/watchlist + /api/universe tests."""

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


async def test_get_universe_default(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/universe")
    assert r.status_code == 200
    body = r.json()
    assert "NVDA" in body["tickers"]


async def test_add_universe_idempotent(client_setup) -> None:
    _, client = client_setup
    r1 = client.post("/api/universe", json={"tickers": ["XYZ"]})
    assert r1.status_code == 200
    assert "XYZ" in r1.json()["tickers"]
    r2 = client.post("/api/universe", json={"tickers": ["XYZ"]})
    assert r2.status_code == 200
    # Still only one XYZ (set semantics in service layer)
    assert r2.json()["tickers"].count("XYZ") == 1


async def test_remove_universe(client_setup) -> None:
    _, client = client_setup
    client.post("/api/universe", json={"tickers": ["ZZZ"]})
    r = client.delete("/api/universe/ZZZ")
    assert r.status_code == 200
    assert "ZZZ" not in r.json()["tickers"]


async def test_get_today_watchlist(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/watchlist/today")
    assert r.status_code == 200
    body = r.json()
    assert "tickers" in body


async def test_set_watchlist(client_setup) -> None:
    _, client = client_setup
    r = client.put(
        "/api/watchlist",
        json={"tickers": ["NVDA", "AMD"], "notes": "tested"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "NVDA" in body["tickers"]
    assert "AMD" in body["tickers"]


async def test_set_watchlist_rejects_unknown_ticker(client_setup) -> None:
    _, client = client_setup
    r = client.put(
        "/api/watchlist",
        json={"tickers": ["UNKNOWN_TICKER"]},
    )
    assert r.status_code == 400


async def test_history_returns_entries(client_setup) -> None:
    _, client = client_setup
    client.put("/api/watchlist", json={"tickers": ["NVDA"]})
    r = client.get("/api/watchlist/history?days=5")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1
