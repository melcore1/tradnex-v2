"""Nightly calendar refresh task tests."""

import pytest

from services.data.calendar_refresh_task import refresh_calendar_cache
from shared.clients.mock_calendar import MockCalendarClient


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "crt.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


async def test_refresh_writes_events(db_conn) -> None:
    client = MockCalendarClient()
    universe = ["NVDA", "AMD", "SPY"]
    econ_count, earn_count = await refresh_calendar_cache(
        client, db_conn, universe, horizon_days=60
    )
    # Mock auto-seeds 3 economic events; only those within 60 days count
    assert econ_count >= 1
    # Earnings: at least the universe tickers' first event
    assert earn_count >= 1
    total = db_conn.execute("SELECT COUNT(*) FROM calendar_cache").fetchone()[0]
    assert total == econ_count + earn_count


async def test_refresh_idempotent_same_data(db_conn) -> None:
    client = MockCalendarClient()
    universe = ["NVDA", "AMD"]
    await refresh_calendar_cache(client, db_conn, universe, horizon_days=60)
    count_first = db_conn.execute("SELECT COUNT(*) FROM calendar_cache").fetchone()[0]
    await refresh_calendar_cache(client, db_conn, universe, horizon_days=60)
    count_second = db_conn.execute("SELECT COUNT(*) FROM calendar_cache").fetchone()[0]
    assert count_first == count_second  # UNIQUE constraint dedupes


async def test_universe_filter_applied(db_conn) -> None:
    """Earnings filter to universe; events for non-universe tickers excluded."""
    client = MockCalendarClient()
    await refresh_calendar_cache(client, db_conn, ["NVDA"], horizon_days=120)
    earn_tickers = db_conn.execute(
        "SELECT DISTINCT ticker FROM calendar_cache WHERE event_type = 'earnings'"
    ).fetchall()
    tickers = {row["ticker"] for row in earn_tickers}
    assert tickers == {"NVDA"}
