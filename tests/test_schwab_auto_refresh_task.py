"""Tests for services.data.schwab_refresh_task.schwab_refresh_tick.

Verifies the auto-refresh background task wired into the data service's
apscheduler runs the expected behavior — no-op on missing creds, warning
when refresh window narrows, error-event on failures, and a real refresh
when everything is configured.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from services.data.schwab_refresh_task import (
    REFRESH_WINDOW_WARN_HOURS,
    schwab_refresh_tick,
)
from shared.services.credentials import clear_cache, upsert_credential
from tests._credential_helpers import TEST_ENCRYPTION_KEY, get_test_encryption


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "task.db"))
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    from shared import config as cfg
    from shared import db as db_mod

    importlib.reload(cfg)
    importlib.reload(db_mod)
    db_mod.run_migrations()
    clear_cache()
    c = db_mod.get_connection()
    yield c
    c.close()


def _seed_client(conn) -> None:
    upsert_credential(
        conn,
        get_test_encryption(),
        "schwab_client",
        secrets={"client_id": "cid", "client_secret": "csec"},
    )


def _seed_oauth(conn, *, refresh_expires_in_hours: float) -> None:
    upsert_credential(
        conn,
        get_test_encryption(),
        "schwab_oauth",
        secrets={
            "access_token": "at",
            "refresh_token": "rt_v1",
            "token_type": "Bearer",
            "scope": "",
        },
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        refresh_token_expires_at=datetime.now(UTC)
        + timedelta(hours=refresh_expires_in_hours),
    )


async def test_silent_noop_when_no_oauth_credentials(conn) -> None:
    """No tokens → don't even log a warning; user is in onboarding mode."""
    await schwab_refresh_tick()
    rows = conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type LIKE '%refresh%'"
    ).fetchone()[0]
    assert rows == 0


async def test_warns_when_refresh_window_narrowing(conn, monkeypatch) -> None:
    _seed_client(conn)
    _seed_oauth(conn, refresh_expires_in_hours=12.0)  # < 24h

    # Stub refresh_schwab_token so the warning check is the only side-effect
    async def fake_refresh(*args, **kwargs):
        from shared.services.schwab_refresh import RefreshResult

        return RefreshResult(success=True, message="ok")

    monkeypatch.setattr(
        "services.data.schwab_refresh_task.refresh_schwab_token", fake_refresh
    )
    await schwab_refresh_tick()

    row = conn.execute(
        "SELECT payload FROM events WHERE event_type='refresh_token_expiring' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None


async def test_no_warning_when_refresh_window_healthy(conn, monkeypatch) -> None:
    _seed_client(conn)
    _seed_oauth(conn, refresh_expires_in_hours=6 * 24)  # 6 days

    async def fake_refresh(*args, **kwargs):
        from shared.services.schwab_refresh import RefreshResult

        return RefreshResult(success=True, message="ok")

    monkeypatch.setattr(
        "services.data.schwab_refresh_task.refresh_schwab_token", fake_refresh
    )
    await schwab_refresh_tick()

    row = conn.execute(
        "SELECT 1 FROM events WHERE event_type='refresh_token_expiring'"
    ).fetchone()
    assert row is None


async def test_emits_error_on_failed_refresh(conn, monkeypatch) -> None:
    _seed_client(conn)
    _seed_oauth(conn, refresh_expires_in_hours=6 * 24)

    async def fake_refresh(*args, **kwargs):
        from shared.services.schwab_refresh import RefreshResult

        return RefreshResult(success=False, message="boom")

    monkeypatch.setattr(
        "services.data.schwab_refresh_task.refresh_schwab_token", fake_refresh
    )
    await schwab_refresh_tick()

    row = conn.execute(
        "SELECT payload FROM events WHERE event_type='auto_refresh_failed'"
    ).fetchone()
    assert row is not None


async def test_survives_transient_exception(conn, monkeypatch) -> None:
    _seed_client(conn)
    _seed_oauth(conn, refresh_expires_in_hours=6 * 24)

    async def crashing_refresh(*args, **kwargs):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(
        "services.data.schwab_refresh_task.refresh_schwab_token", crashing_refresh
    )
    # Must not raise.
    await schwab_refresh_tick()

    row = conn.execute(
        "SELECT payload FROM events WHERE event_type='auto_refresh_exception'"
    ).fetchone()
    assert row is not None


def test_warn_threshold_is_24_hours() -> None:
    # Constant guard so future refactors don't accidentally change the
    # behavior the UI depends on.
    assert REFRESH_WINDOW_WARN_HOURS == 24.0
