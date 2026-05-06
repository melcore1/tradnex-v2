"""/api/dashboard tests."""

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


async def test_summary_returns_required_fields(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/dashboard/summary")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "open_positions_count",
        "pending_human_approvals",
        "pending_llm_evaluations",
        "recent_events",
        "system_status",
    ):
        assert key in body


async def test_morning_view_returns_universe_and_calendar(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/dashboard/morning-view")
    assert r.status_code == 200
    body = r.json()
    assert "universe" in body
    assert isinstance(body["universe"], list)
    assert "upcoming_calendar" in body


async def test_active_trades_empty_when_no_positions(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/dashboard/active-trades")
    assert r.status_code == 200
    assert r.json() == []


async def test_journal_returns_summary_for_today(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/dashboard/journal")
    assert r.status_code == 200
    body = r.json()
    assert "scanner_cycles_run" in body
    assert "candidates_fired" in body
    assert "decisions" in body


async def test_journal_for_explicit_date(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/dashboard/journal?date=2026-01-01")
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == "2026-01-01"
