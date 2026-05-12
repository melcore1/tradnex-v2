"""correlation_check — pairwise correlation from the cached matrix.

Reads ``correlation_snapshots`` (populated nightly by Phase 1d's correlation
job). Returns a friendly note when the pair isn't in the cache rather than
running a live computation (those take seconds per ticker pair).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from services.mcp.deps import db_session
from shared.analytics.correlation import get_correlation_matrix


def _interpret(corr: Decimal) -> str:
    abs_c = abs(corr)
    direction = "positive" if corr >= 0 else "negative"
    if abs_c < Decimal("0.2"):
        magnitude = "weak"
    elif abs_c < Decimal("0.5"):
        magnitude = "moderate"
    elif abs_c < Decimal("0.8"):
        magnitude = "strong"
    else:
        magnitude = "very strong"
    return f"{magnitude} {direction}"


async def correlation_check(
    ticker_a: str,
    ticker_b: str,
) -> dict[str, Any]:
    """Look up pairwise correlation between two tickers."""
    a = ticker_a.upper()
    b = ticker_b.upper()

    with db_session() as conn:
        matrix = get_correlation_matrix([a, b], conn)

    row = matrix.matrix.get(a, {})
    correlation = row.get(b)
    if correlation is None:
        # Try the symmetric lookup before giving up.
        correlation = matrix.matrix.get(b, {}).get(a)

    if correlation is None:
        return {
            "ticker_a": a,
            "ticker_b": b,
            "correlation": None,
            "note": (
                "Pair not in correlation_snapshots cache. Both tickers must be "
                "in the universe and the nightly correlation job must have run."
            ),
            "as_of": matrix.timestamp.isoformat(),
        }

    return {
        "ticker_a": a,
        "ticker_b": b,
        "correlation": str(correlation),
        "lookback_days": matrix.lookback_days,
        "interpretation": _interpret(correlation),
        "as_of": matrix.timestamp.isoformat(),
    }
