"""option_chain — filtered options chain decorated for LLM contract picking.

Returns a list of decorated contracts (raw fields + computed signals like
liquidity_pass, probability_itm, breakeven, mispricing_pct, dte_bucket)
alongside a chain-wide `context` block (spot, iv_rank, expected_move_1sigma,
regime labels). The LLM uses these signals to recommend ONE contract.

Defaults reflect the tastytrade directional sweet spot: 21-45 DTE, |delta|
0.20-0.80. Override via params for weeklies (max_dte=7), credit-spread shorts
(delta_min=0.15, delta_max=0.25), or a specific expiry
(expiration="2026-06-19").
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import date
from typing import Any

from services.mcp.deps import db_session
from services.mcp.formatters import (
    format_chain_context,
    format_option_contract,
)
from shared.analytics import compute_options_analysis
from shared.clients.market_data import ContractTypeFilter, MarketDataClient
from shared.schemas.market import OptionContract, OptionsChain

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


async def option_chain(
    ticker: str,
    min_dte: int = 21,
    max_dte: int = 45,
    contract_type: ContractTypeFilter = "both",
    delta_min: float = 0.20,
    delta_max: float = 0.80,
    expiration: str | None = None,
    limit: int = DEFAULT_LIMIT,
    *,
    client: MarketDataClient,
) -> dict[str, Any]:
    """Fetch the chain, apply filters, decorate, and return."""
    ticker = ticker.upper()
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    if delta_min < 0 or delta_max > 1 or delta_min > delta_max:
        raise ValueError(
            "delta_min/delta_max must satisfy 0 <= delta_min <= delta_max <= 1"
        )
    if contract_type not in ("call", "put", "both"):
        raise ValueError("contract_type must be 'call', 'put', or 'both'")

    target_exp: date | None = None
    if expiration:
        try:
            target_exp = date.fromisoformat(expiration)
        except ValueError as e:
            raise ValueError(
                f"expiration must be ISO date (YYYY-MM-DD); got {expiration!r}"
            ) from e

    # Fetch chain. When the caller pinned a specific expiry, widen the
    # client-side DTE bounds so we don't accidentally filter it out at the
    # Schwab request layer; we'll filter back down by date below.
    fetch_min = 0 if target_exp else min_dte
    fetch_max = 365 if target_exp else max_dte
    chain = await client.get_options_chain(
        ticker,
        min_dte=fetch_min,
        max_dte=fetch_max,
        contract_type=contract_type,
    )

    candidates = _apply_filters(
        chain.contracts,
        target_exp=target_exp,
        delta_min=delta_min,
        delta_max=delta_max,
    )

    # Sort: closest strike to spot first, then closest-to-30-DTE within that.
    spot = chain.spot_at_fetch
    candidates.sort(key=lambda c: (
        abs(float(c.strike - spot)),
        abs(c.dte - 30),
    ))
    contracts_out = candidates[:limit]

    # Chain-wide analytics (need DB for IV-rank lookback). Offload the sync
    # compute to a worker thread so we don't block the event loop on a 500-
    # contract chain.
    analysis = await asyncio.to_thread(_compute_options_sync, chain)

    return {
        "ticker": ticker,
        "context": format_chain_context(chain, analysis),
        "contracts": [
            format_option_contract(c, analysis) for c in contracts_out
        ],
        "filtered_count": len(contracts_out),
        "total_available": len(chain.contracts),
        "filters": {
            "min_dte": min_dte,
            "max_dte": max_dte,
            "contract_type": contract_type,
            "delta_min": delta_min,
            "delta_max": delta_max,
            "expiration": expiration,
            "limit": limit,
        },
        "as_of": chain.timestamp.isoformat(),
    }


def _apply_filters(
    contracts: list[OptionContract],
    *,
    target_exp: date | None,
    delta_min: float,
    delta_max: float,
) -> list[OptionContract]:
    """Apply expiration + delta-band filters."""
    out = contracts
    if target_exp is not None:
        out = [c for c in out if c.expiration == target_exp]
    # |delta| band — covers both calls (positive delta) and puts (negative).
    out = [
        c for c in out
        if delta_min <= abs(float(c.delta)) <= delta_max
    ]
    return out


def _compute_options_sync(chain: OptionsChain) -> Any:
    """Run compute_options_analysis with its own DB connection."""
    with db_session() as conn:
        return compute_options_analysis(chain, conn)


__all__ = ["option_chain", "DEFAULT_LIMIT", "MAX_LIMIT"]


# Suppress unused-import warning for sqlite3 (used implicitly via db_session).
_ = sqlite3
