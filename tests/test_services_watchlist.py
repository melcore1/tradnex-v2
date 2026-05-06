"""Watchlist service tests."""

import json

import pytest

from shared.services.universe import TickerNotInUniverseError
from shared.services.watchlist import (
    add_ticker_to_watchlist,
    get_active_watchlist,
    get_per_ticker_overrides,
    get_watchlist_history,
    remove_ticker_from_watchlist,
    set_watchlist,
    validate_watchlist_universe_sync,
)
from shared.util.dates import today_et


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "wl.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


async def test_get_active_when_no_rows_returns_empty_system_entry(db_conn) -> None:
    entry = await get_active_watchlist(db_conn)
    assert entry.tickers == []
    assert entry.created_by == "system"
    assert entry.date == today_et()


async def test_get_active_returns_today_when_present(db_conn) -> None:
    await set_watchlist(db_conn, ["NVDA", "AMD"])
    entry = await get_active_watchlist(db_conn)
    assert entry.tickers == ["NVDA", "AMD"]
    assert entry.created_by == "manual"


async def test_get_active_carries_forward_yesterday(db_conn) -> None:
    # Manually insert a row for a prior date
    db_conn.execute(
        "INSERT INTO watchlists "
        "(date, tickers_json, per_ticker_overrides_json, notes, created_ts, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("2025-12-01", json.dumps(["SPY", "QQQ"]), "{}", None, 0.0, "manual"),
    )
    db_conn.commit()
    entry = await get_active_watchlist(db_conn)
    assert entry.created_by == "auto_carry_forward"
    assert entry.tickers == ["SPY", "QQQ"]
    assert entry.per_ticker_overrides == {}  # overrides not carried


async def test_set_watchlist_with_invalid_ticker_raises(db_conn) -> None:
    with pytest.raises(TickerNotInUniverseError):
        await set_watchlist(db_conn, ["NVDA", "BOGUS"])


async def test_set_watchlist_idempotent_per_date(db_conn) -> None:
    await set_watchlist(db_conn, ["NVDA"])
    await set_watchlist(db_conn, ["AMD", "SPY"])
    rows = db_conn.execute("SELECT COUNT(*) FROM watchlists").fetchone()
    assert rows[0] == 1
    entry = await get_active_watchlist(db_conn)
    assert entry.tickers == ["AMD", "SPY"]


async def test_add_ticker_creates_row_when_absent(db_conn) -> None:
    entry = await add_ticker_to_watchlist(db_conn, "NVDA")
    assert "NVDA" in entry.tickers


async def test_add_ticker_to_existing(db_conn) -> None:
    await set_watchlist(db_conn, ["NVDA"])
    entry = await add_ticker_to_watchlist(db_conn, "AMD")
    assert sorted(entry.tickers) == ["AMD", "NVDA"]


async def test_remove_ticker_works(db_conn) -> None:
    await set_watchlist(db_conn, ["NVDA", "AMD"])
    entry = await remove_ticker_from_watchlist(db_conn, "NVDA")
    assert entry.tickers == ["AMD"]


async def test_history_returns_last_n(db_conn) -> None:
    db_conn.execute(
        "INSERT INTO watchlists "
        "(date, tickers_json, per_ticker_overrides_json, notes, created_ts, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("2025-12-01", json.dumps(["SPY"]), "{}", None, 0.0, "manual"),
    )
    db_conn.execute(
        "INSERT INTO watchlists "
        "(date, tickers_json, per_ticker_overrides_json, notes, created_ts, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("2025-12-02", json.dumps(["QQQ"]), "{}", None, 0.0, "manual"),
    )
    db_conn.commit()
    history = await get_watchlist_history(db_conn, days=10)
    assert len(history) == 2


async def test_get_per_ticker_overrides_empty(db_conn) -> None:
    overrides = await get_per_ticker_overrides(db_conn, "NVDA")
    assert overrides == {}


async def test_get_per_ticker_overrides_set(db_conn) -> None:
    await add_ticker_to_watchlist(db_conn, "NVDA", overrides={"rsi_min": 60})
    overrides = await get_per_ticker_overrides(db_conn, "NVDA")
    assert overrides == {"rsi_min": 60}


async def test_validate_sync_returns_drift(db_conn) -> None:
    # Manually insert a watchlist with a ticker not in universe
    db_conn.execute(
        "INSERT INTO watchlists "
        "(date, tickers_json, per_ticker_overrides_json, notes, created_ts, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (today_et(), json.dumps(["NVDA", "DRIFT"]), "{}", None, 0.0, "manual"),
    )
    db_conn.commit()
    drift = await validate_watchlist_universe_sync(db_conn)
    assert "DRIFT" in drift


async def test_validate_sync_clean(db_conn) -> None:
    await set_watchlist(db_conn, ["NVDA", "AMD"])
    drift = await validate_watchlist_universe_sync(db_conn)
    assert drift == []
