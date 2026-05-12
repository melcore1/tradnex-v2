"""regime_check — categorical market-regime classification for a single ticker.

Combines Tier 2 (trend/volatility/momentum) with Tier 3 (gamma + IV) signals
via the existing `classify_regime` helper.
"""

from __future__ import annotations

import asyncio
from typing import Any

from services.mcp.deps import db_session
from services.mcp.formatters import format_regime
from shared.analytics import (
    compute_full_analysis,
    compute_options_analysis,
)
from shared.clients.market_data import MarketDataClient


async def regime_check(
    ticker: str,
    client: MarketDataClient,
) -> dict[str, Any]:
    """Return the overall regime + per-axis breakdown."""
    ticker = ticker.upper()
    bars_task = client.get_bars(ticker, timeframe="1d", limit=60)
    chain_task = client.get_options_chain(ticker, min_dte=0, max_dte=14)
    bars, chain = await asyncio.gather(bars_task, chain_task)

    options_analysis = None
    if chain.contracts:
        options_analysis = await asyncio.to_thread(_compute_options_sync, chain)

    full = await compute_full_analysis(
        ticker, bars, options_analysis=options_analysis
    )
    return {
        "ticker": ticker,
        **format_regime(full.regime),
        "as_of": full.timestamp.isoformat(),
    }


def _compute_options_sync(chain: Any) -> Any:
    """Run sync options analysis with a fresh DB connection."""
    with db_session() as conn:
        return compute_options_analysis(chain, conn)
