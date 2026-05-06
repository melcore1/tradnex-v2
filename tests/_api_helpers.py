"""Shared helpers for /api/* tests using FastAPI TestClient."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient


def reset_modules_for_test_db(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Set DATABASE_PATH to a tmp file and reload config/db so the sqlite
    connection points at the right place. Returns a connection."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")  # TestClient is HTTP

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    return db_mod.get_connection()


def build_test_client() -> TestClient:
    """Reload services.api.main so it picks up the patched config."""
    import services.api.main as api_main
    importlib.reload(api_main)
    return TestClient(api_main.app)


async def seed_user(
    conn: Any,
    email: str = "test@example.com",
    password: str = "testpass1234",
) -> Any:
    from shared.services.auth import create_user
    return await create_user(conn, email, password)


def login_test_client(
    client: TestClient, email: str = "test@example.com", password: str = "testpass1234"
) -> dict[str, Any]:
    """Login via API; cookie persists on the client."""
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def auth_client(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Any, TestClient]]:
    """Yield (db_conn, logged-in TestClient). For sync test functions
    use this; for async, build it inline."""
    raise NotImplementedError("Use the async db_conn + setup pattern in each test")
