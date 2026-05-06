"""Portfolio Greeks against real positions in the database."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from shared.analytics.options.greeks_aggregation import (
    PortfolioGreeksResult,
    portfolio_greeks,
)
from shared.clients.market_data import MarketDataClient
from shared.schemas.core import Position
from shared.schemas.market import OptionContract


def empty_portfolio_greeks(spot: Decimal = Decimal("0")) -> PortfolioGreeksResult:
    zero = Decimal("0")
    return PortfolioGreeksResult(
        timestamp=datetime.now(UTC),
        bars_used=0,
        spot=spot,
        net_delta=zero,
        net_gamma=zero,
        net_theta=zero,
        net_vega=zero,
        net_rho=zero,
        dollar_delta=zero,
        dollar_gamma=zero,
        concentration_warnings=[],
        positions_count=0,
    )


def _row_to_position(row: Any) -> Position:
    """Adapt a sqlite3.Row tuple to the Position model."""
    return Position(
        id=row[0],
        candidate_id=row[1],
        ticker=str(row[2]),
        contract_symbol=str(row[3]),
        side=row[4],
        quantity=int(row[5]),
        entry_price=Decimal(str(row[6])),
        entry_ts=float(row[7]),
        exit_price=Decimal(str(row[8])) if row[8] is not None else None,
        exit_ts=float(row[9]) if row[9] is not None else None,
        exit_reason=str(row[10]) if row[10] is not None else None,
        pnl=Decimal(str(row[11])) if row[11] is not None else None,
        status=row[12],
    )


async def get_current_portfolio_greeks(
    client: MarketDataClient,
    conn: sqlite3.Connection,
) -> PortfolioGreeksResult:
    """Greeks across every open position in the DB. Empty when none exist."""
    rows = conn.execute(
        "SELECT id, candidate_id, ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts, exit_price, exit_ts, exit_reason, pnl, status "
        "FROM positions WHERE status = 'open'"
    ).fetchall()

    if not rows:
        return empty_portfolio_greeks()

    positions = [_row_to_position(r) for r in rows]
    chain_lookup: dict[str, OptionContract] = {}
    underlyings_seen: set[str] = set()
    spot = Decimal("0")
    for pos in positions:
        if pos.ticker in underlyings_seen:
            continue
        underlyings_seen.add(pos.ticker)
        chain = await client.get_options_chain(pos.ticker)
        if spot == 0:
            spot = chain.spot_at_fetch
        for contract in chain.contracts:
            chain_lookup[contract.symbol] = contract

    return portfolio_greeks(positions, chain_lookup, spot)
