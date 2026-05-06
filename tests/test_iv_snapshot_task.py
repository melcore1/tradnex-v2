"""IV snapshot task tests: writes to daily_iv_snapshots, idempotent."""


import pytest

from services.data.iv_snapshot_task import snapshot_iv_for_ticker
from shared.clients.mock_market_data import MockDataClient


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "snap.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


async def test_snapshot_writes_row(db_conn) -> None:
    client = MockDataClient(seed=42)
    written = await snapshot_iv_for_ticker("NVDA", client, conn=db_conn)
    assert written is True
    rows = db_conn.execute(
        "SELECT ticker, atm_iv FROM daily_iv_snapshots WHERE ticker = ?",
        ("NVDA",),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "NVDA"
    assert float(rows[0][1]) > 0


async def test_snapshot_idempotent_same_day(db_conn) -> None:
    client = MockDataClient(seed=42)
    await snapshot_iv_for_ticker("NVDA", client, conn=db_conn)
    await snapshot_iv_for_ticker("NVDA", client, conn=db_conn)
    rows = db_conn.execute(
        "SELECT COUNT(*) FROM daily_iv_snapshots WHERE ticker = ?",
        ("NVDA",),
    ).fetchall()
    assert rows[0][0] == 1


async def test_mock_seed_iv_history_populates_252_days(db_conn) -> None:
    client = MockDataClient(seed=42)
    written = client.seed_iv_history()
    assert written > 0
    # 10 baseline tickers × 252 days
    rows = db_conn.execute(
        "SELECT COUNT(DISTINCT date) FROM daily_iv_snapshots WHERE ticker = ?",
        ("NVDA",),
    ).fetchall()
    assert rows[0][0] >= 200


async def test_mock_seed_idempotent(db_conn) -> None:
    client = MockDataClient(seed=42)
    first = client.seed_iv_history()
    second = client.seed_iv_history()
    assert first > 0
    assert second == 0  # Already seeded — instance flag short-circuits


async def test_iv_rank_works_after_mock_seeding(db_conn) -> None:
    """End-to-end: seed history, snapshot today, then iv_rank reads both."""
    from shared.analytics import iv_rank

    client = MockDataClient(seed=42)
    client.seed_iv_history()
    await snapshot_iv_for_ticker("NVDA", client, conn=db_conn)

    chain = await client.get_options_chain("NVDA", max_dte=45)
    spot = chain.spot_at_fetch
    atm = min(chain.contracts, key=lambda c: abs(c.strike - spot))
    result = iv_rank("NVDA", atm.iv, db_conn)
    assert result.data_points > 0
