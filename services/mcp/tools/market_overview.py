"""market_overview — top gainers / losers / most active from Schwab movers.

Drop-in shape compatible with the legacy Scout `market_overview`. Crypto mode
returns an informational error (Schwab data layer is equities/options only).
"""

from __future__ import annotations

from typing import Any, Literal

from services.mcp.formatters import format_mover
from shared.clients.market_data import MarketDataClient


async def market_overview(
    market_type: Literal["stocks", "crypto"],
    client: MarketDataClient,
) -> dict[str, Any]:
    """Most-active / top-gainers / top-losers snapshot."""
    if market_type == "crypto":
        return {
            "error": "Crypto movers not available via the Schwab data layer.",
            "note": "TradNex 2 ingests Schwab equities/options only.",
            "market_type": market_type,
        }

    movers = await client.get_movers()
    return {
        "market_type": market_type,
        "most_active": [format_mover(m) for m in movers.most_active[:10]],
        "top_gainers": [format_mover(m) for m in movers.top_gainers[:10]],
        "top_losers": [format_mover(m) for m in movers.top_losers[:10]],
        "as_of": movers.timestamp.isoformat(),
    }
