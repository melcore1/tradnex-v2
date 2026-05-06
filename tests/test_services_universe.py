"""Universe service tests."""

import pytest

from shared.services.universe import (
    DEFAULT_UNIVERSE,
    InvalidTickerError,
    add_to_universe,
    get_universe,
    is_in_universe,
    remove_from_universe,
)
from shared.services.watchlist import set_watchlist


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "u.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


async def test_default_universe_seeded(db_conn) -> None:
    universe = await get_universe(db_conn)
    assert "NVDA" in universe
    assert len(universe) == len(DEFAULT_UNIVERSE)


async def test_add_idempotent(db_conn) -> None:
    await add_to_universe(db_conn, "MSCI")
    await add_to_universe(db_conn, "MSCI")
    universe = await get_universe(db_conn)
    assert universe.count("MSCI") == 1


async def test_remove_ticker(db_conn) -> None:
    await remove_from_universe(db_conn, "NVDA")
    universe = await get_universe(db_conn)
    assert "NVDA" not in universe


async def test_is_in_universe_truth_values(db_conn) -> None:
    assert await is_in_universe(db_conn, "nvda") is True  # case-insensitive
    assert await is_in_universe(db_conn, "BOGUS") is False


async def test_remove_cascades_to_watchlist(db_conn) -> None:
    await set_watchlist(db_conn, ["NVDA", "AMD"])
    await remove_from_universe(db_conn, "NVDA")
    # Watchlist should no longer have NVDA
    rows = db_conn.execute(
        "SELECT tickers_json FROM watchlists ORDER BY date DESC LIMIT 1"
    ).fetchone()
    import json

    tickers = json.loads(rows[0])
    assert "NVDA" not in tickers
    assert "AMD" in tickers


async def test_invalid_ticker_format_rejected(db_conn) -> None:
    with pytest.raises(InvalidTickerError):
        await add_to_universe(db_conn, "BAD TICKER")
    with pytest.raises(InvalidTickerError):
        await add_to_universe(db_conn, "TOOLONGTICKER")
    with pytest.raises(InvalidTickerError):
        await add_to_universe(db_conn, "")
