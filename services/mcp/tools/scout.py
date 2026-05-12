"""scout — full Tier 2 + Tier 3 + regime analysis per ticker.

Drop-in shape compatible with the legacy Scout `scout`. Backed by Schwab
data (Phase 8a.5) and the real TradNex analytics layer, so unlike the
Alpaca-backed predecessor the GEX / IV-rank / skew sections are populated.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

from services.mcp.deps import db_session
from services.mcp.formatters import format_regime, format_tier2, format_tier3
from shared.analytics import (
    compute_full_analysis,
    compute_options_analysis,
)
from shared.clients.market_data import MarketDataClient

MAX_TICKERS_PER_CALL = 10
MAX_DTE_FOR_CHAIN = 14


async def scout(
    ticker: str | list[str],
    days_history: int,
    client: MarketDataClient,
) -> dict[str, Any]:
    """Full quant analysis per ticker; runs tickers in parallel."""
    tickers = [ticker] if isinstance(ticker, str) else list(ticker)
    if not tickers:
        raise ValueError("ticker must not be empty")
    if len(tickers) > MAX_TICKERS_PER_CALL:
        raise ValueError(f"Maximum {MAX_TICKERS_PER_CALL} tickers per call")
    if days_history < 30 or days_history > 500:
        raise ValueError("days_history must be between 30 and 500")

    results = await asyncio.gather(
        *(_one(t.upper(), days_history, client) for t in tickers),
        return_exceptions=True,
    )

    out: dict[str, Any] = {}
    for t, res in zip(tickers, results, strict=False):
        key = t.upper()
        if isinstance(res, BaseException):
            out[key] = {"error": f"{type(res).__name__}: {res}"}
        else:
            out[key] = res

    if len(tickers) == 1:
        single: dict[str, Any] = out[tickers[0].upper()]
        return single
    return out


async def _one(
    ticker: str,
    days_history: int,
    client: MarketDataClient,
) -> dict[str, Any]:
    bars_task = client.get_bars(ticker, timeframe="1d", limit=days_history)
    chain_task = client.get_options_chain(ticker, min_dte=0, max_dte=MAX_DTE_FOR_CHAIN)
    bars, chain = await asyncio.gather(bars_task, chain_task)

    options_block: dict[str, Any] | None = None
    if chain.contracts:
        # compute_options_analysis is sync (pure CPU); offload to threadpool
        # so we don't block the event loop while iterating chain rows.
        options_block = await asyncio.to_thread(_compute_options_sync, chain)

    full = await compute_full_analysis(ticker, bars)

    return {
        "ticker": ticker,
        "spot": str(full.spot),
        "tier2": format_tier2(full),
        "tier3_options": options_block,
        "tier4_regime": format_regime(full.regime),
        "summary": full.summary,
        "as_of": full.timestamp.isoformat(),
    }


def _compute_options_sync(chain: Any) -> dict[str, Any]:
    """Helper to run sync options analysis with its own DB connection."""
    with db_session() as conn:
        analysis = compute_options_analysis(chain, conn)
    return format_tier3(analysis)


__all__ = ["scout", "MAX_TICKERS_PER_CALL"]


# Suppress unused-import warning for sqlite3 (used implicitly via db_session).
_ = sqlite3
