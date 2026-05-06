"""Daily IV snapshot task: pulls ATM IV per ticker and writes to daily_iv_snapshots.

In production this runs once per trading day at ~15:55 ET. In dev with the
mock client, MockDataClient.seed_iv_history() pre-populates 252 days so
iv_rank works immediately.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from shared.clients.market_data import MarketDataClient
from shared.db import get_connection
from shared.events import emit
from shared.schemas.market import OptionsChain

SERVICE_NAME = "data"


def _atm_iv_at_tenor(chain: OptionsChain, target_dte: int) -> Decimal | None:
    """Average ATM IV across calls within 5% of spot at the closest DTE bucket."""
    if not chain.contracts:
        return None
    spot = chain.spot_at_fetch
    by_dte: dict[int, list] = {}
    for c in chain.contracts:
        if c.contract_type != "call":
            continue
        if spot > 0 and abs(c.strike - spot) / spot > Decimal("0.05"):
            continue
        by_dte.setdefault(c.dte, []).append(c)
    if not by_dte:
        return None
    closest = min(by_dte.keys(), key=lambda d: abs(d - target_dte))
    contracts = by_dte[closest]
    return sum((c.iv for c in contracts), Decimal("0")) / Decimal(len(contracts))


async def snapshot_iv_for_ticker(
    ticker: str,
    client: MarketDataClient,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Fetch chain, compute ATM IV at 30/60/90 DTE, persist. Returns True on write."""
    chain = await client.get_options_chain(ticker, max_dte=120)
    if not chain.contracts:
        emit(SERVICE_NAME, "warn", "iv_snapshot_skipped_empty_chain", {"ticker": ticker})
        return False

    spot = chain.spot_at_fetch
    atm_contract = min(chain.contracts, key=lambda c: abs(c.strike - spot))
    atm_iv = atm_contract.iv
    iv_30d = _atm_iv_at_tenor(chain, 30) or atm_iv
    iv_60d = _atm_iv_at_tenor(chain, 60)
    iv_90d = _atm_iv_at_tenor(chain, 90)

    today = datetime.now(UTC).date().isoformat()
    own_conn = conn is None
    db = conn or get_connection()
    try:
        db.execute(
            "INSERT OR REPLACE INTO daily_iv_snapshots "
            "(ticker, date, iv_30d, iv_60d, iv_90d, atm_iv, recorded_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ticker,
                today,
                str(iv_30d),
                str(iv_60d) if iv_60d is not None else None,
                str(iv_90d) if iv_90d is not None else None,
                str(atm_iv),
                datetime.now(UTC).timestamp(),
            ),
        )
        db.commit()
    finally:
        if own_conn:
            db.close()

    emit(
        SERVICE_NAME,
        "info",
        "iv_snapshot_recorded",
        {"ticker": ticker, "iv_30d": str(iv_30d), "atm_iv": str(atm_iv)},
    )
    return True


def next_close_minus_5min(now: datetime | None = None) -> datetime:
    """Compute next 15:55 ET (≈ 19:55 UTC during DST) for scheduling."""
    n = now or datetime.now(UTC)
    candidate = datetime.combine(n.date(), time(19, 55), tzinfo=UTC)
    if candidate <= n or n.weekday() >= 5:
        # next weekday
        days_ahead = 1
        while True:
            d = (n + timedelta(days=days_ahead)).date()
            if datetime(d.year, d.month, d.day).weekday() < 5:
                return datetime.combine(d, time(19, 55), tzinfo=UTC)
            days_ahead += 1
    return candidate
