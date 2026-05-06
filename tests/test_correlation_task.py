"""Nightly correlation task tests."""

import json

import pytest

from services.data.correlation_task import _load_universe, run_correlation_task
from shared.clients.mock_market_data import MockDataClient


@pytest.fixture
def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ctask.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


async def test_writes_to_correlation_snapshots(db_conn) -> None:
    client = MockDataClient(seed=42)
    written = await run_correlation_task(client, db_conn, lookback_days=30)
    assert written > 0
    rows = db_conn.execute(
        "SELECT COUNT(*) FROM correlation_snapshots"
    ).fetchone()
    assert rows[0] == written


async def test_idempotent_same_day(db_conn) -> None:
    client = MockDataClient(seed=42)
    first = await run_correlation_task(client, db_conn, lookback_days=30)
    second = await run_correlation_task(client, db_conn, lookback_days=30)
    rows = db_conn.execute(
        "SELECT COUNT(*) FROM correlation_snapshots"
    ).fetchone()
    # Same date → INSERT OR REPLACE keeps row count constant (== first run's row count)
    assert rows[0] == first
    assert second == first


async def test_universe_falls_back_to_baselines_when_unset(db_conn) -> None:
    universe = _load_universe(db_conn)
    # Default strategy_config has empty settings_json '{}', so we fall through
    # to the MockDataClient baseline list (10 tickers).
    assert "NVDA" in universe
    assert len(universe) >= 5


async def test_universe_reads_from_strategy_config(db_conn) -> None:
    db_conn.execute(
        "UPDATE strategy_configs SET settings_json = ? WHERE name = 'default'",
        (json.dumps({"universe": ["AAA", "BBB"]}),),
    )
    db_conn.commit()
    universe = _load_universe(db_conn)
    assert universe == ["AAA", "BBB"]
