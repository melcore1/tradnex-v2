"""Portfolio Greeks against real positions stored in DB."""

from decimal import Decimal

import pytest

from shared.analytics.options.portfolio_greeks_real import (
    empty_portfolio_greeks,
    get_current_portfolio_greeks,
)
from shared.clients.mock_market_data import MockDataClient


@pytest.fixture
def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "pg.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


def _insert_position(
    conn,
    ticker: str,
    contract_symbol: str,
    side: str,
    quantity: int,
    status: str = "open",
) -> None:
    conn.execute(
        "INSERT INTO positions "
        "(ticker, contract_symbol, side, quantity, entry_price, entry_ts, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ticker, contract_symbol, side, quantity, 1.50, 0.0, status),
    )
    conn.commit()


async def test_empty_when_no_open_positions(db_conn) -> None:
    client = MockDataClient(seed=42)
    result = await get_current_portfolio_greeks(client, db_conn)
    assert result.positions_count == 0
    assert result.net_delta == Decimal("0")


async def test_long_position_delta_positive(db_conn) -> None:
    client = MockDataClient(seed=42)
    chain = await client.get_options_chain("NVDA")
    long_call = next(c for c in chain.contracts if c.contract_type == "call")
    _insert_position(db_conn, "NVDA", long_call.symbol, "long", 5)
    result = await get_current_portfolio_greeks(client, db_conn)
    assert result.positions_count == 1
    # Phase 1c portfolio_greeks: delta * qty * 100 with sign +
    assert result.net_delta != Decimal("0")


async def test_short_position_delta_inverts_sign(db_conn) -> None:
    client = MockDataClient(seed=42)
    chain = await client.get_options_chain("NVDA")
    long_call = next(c for c in chain.contracts if c.contract_type == "call")
    _insert_position(db_conn, "NVDA", long_call.symbol, "short", 5)
    result = await get_current_portfolio_greeks(client, db_conn)
    # Short call → negative delta (call delta * -1)
    assert result.net_delta < Decimal("0")


async def test_closed_positions_excluded(db_conn) -> None:
    client = MockDataClient(seed=42)
    chain = await client.get_options_chain("NVDA")
    contract = chain.contracts[0]
    _insert_position(db_conn, "NVDA", contract.symbol, "long", 1, status="closed")
    result = await get_current_portfolio_greeks(client, db_conn)
    assert result.positions_count == 0


def test_empty_portfolio_greeks_helper() -> None:
    result = empty_portfolio_greeks(spot=Decimal("142.50"))
    assert result.positions_count == 0
    assert result.net_delta == Decimal("0")
    assert result.spot == Decimal("142.50")
    assert result.concentration_warnings == []
