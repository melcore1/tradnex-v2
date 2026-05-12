"""quick_check — lightweight position-monitoring snapshot per ticker.

Drop-in shape compatible with the legacy Scout `quick_check`. For a single
ticker, returns a flat dict; for a list of tickers, returns a dict-of-dicts
keyed by ticker. Errors on any one ticker are isolated (return ``{"error":
...}``) so a bad symbol can't poison the batch.
"""

from __future__ import annotations

import asyncio
from typing import Any

from services.mcp.formatters import _s, format_quote
from shared.analytics import compute_full_analysis
from shared.clients.market_data import MarketDataClient

MAX_TICKERS_PER_CALL = 10


async def quick_check(
    ticker: str | list[str],
    client: MarketDataClient,
) -> dict[str, Any]:
    """Run a lightweight per-ticker snapshot in parallel."""
    tickers = [ticker] if isinstance(ticker, str) else list(ticker)
    if not tickers:
        raise ValueError("ticker must not be empty")
    if len(tickers) > MAX_TICKERS_PER_CALL:
        raise ValueError(f"Maximum {MAX_TICKERS_PER_CALL} tickers per call")

    results = await asyncio.gather(
        *(_one(t.upper(), client) for t in tickers),
        return_exceptions=True,
    )

    out: dict[str, Any] = {}
    for t, res in zip(tickers, results, strict=False):
        key = t.upper()
        if isinstance(res, BaseException):
            out[key] = {"error": f"{type(res).__name__}: {res}"}
        else:
            out[key] = res

    # Single ticker → flat dict to match Scout's shape.
    if len(tickers) == 1:
        single: dict[str, Any] = out[tickers[0].upper()]
        return single
    return out


async def _one(ticker: str, client: MarketDataClient) -> dict[str, Any]:
    """Compute quick_check for a single ticker."""
    quote_task = client.get_quote(ticker)
    bars_task = client.get_bars(ticker, timeframe="1d", limit=60)
    quote, bars = await asyncio.gather(quote_task, bars_task)

    analysis = await compute_full_analysis(ticker, bars)

    return {
        **format_quote(quote),
        "rsi_14": _s(analysis.rsi.latest),
        "rsi_trend": analysis.rsi.trend,
        "atr_pct_of_spot": _s(analysis.atr.latest_pct_of_spot),
        "atr_regime": analysis.atr.regime,
        "ema9": _s(analysis.ema9.latest),
        "ema21": _s(analysis.ema21.latest),
        "above_200_sma": analysis.above_200_sma,
        "nearest_support": _s(analysis.support_resistance.nearest_support),
        "nearest_resistance": _s(analysis.support_resistance.nearest_resistance),
        "summary": analysis.summary,
    }
