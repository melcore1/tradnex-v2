"""0DTE-specific analysis: returned only when today is an expiration day."""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Literal

from shared.analytics.base import IndicatorResult, to_decimal
from shared.analytics.options.flow import expected_move
from shared.analytics.options.gex import gex_per_strike
from shared.analytics.options.pain import max_pain
from shared.schemas.market import OptionsChain

PinRisk = Literal["high", "moderate", "low"]


class ZeroDTEResult(IndicatorResult):
    underlying: str
    expiration: object  # date — using object to avoid pydantic forwarding quirks
    time_to_expiry_hours: Decimal
    pin_risk: PinRisk
    expected_move: Decimal
    expected_move_pct: Decimal
    gamma_concentration: Decimal
    key_strikes: list[Decimal]


def zero_dte_analysis(
    chain: OptionsChain,
    current_dt: datetime | None = None,
) -> ZeroDTEResult | None:
    """Return None unless today is an expiration day represented in the chain."""
    now = current_dt or datetime.now(UTC)
    today = now.date()
    if today not in chain.expirations:
        return None
    contracts = chain.for_expiration(today)
    if not contracts:
        return None

    # Time to expiry: assume close at 16:00 ET. We approximate ET as UTC-04:00
    # (DST-light); precise-tz handling lives in market_status, not here.
    expiry_dt = datetime.combine(today, time(20, 0), tzinfo=UTC)
    hours = max((expiry_dt - now).total_seconds() / 3600.0, 0.0)

    mp = max_pain(chain, expiration=today)
    if mp.distance_pct < Decimal("0.3"):
        pin_risk: PinRisk = "high"
    elif mp.distance_pct < Decimal("1.0"):
        pin_risk = "moderate"
    else:
        pin_risk = "low"

    em = expected_move(chain, expiration=today)
    full_gex = gex_per_strike(chain)
    today_gex = gex_per_strike(chain, expiration=today)
    if abs(full_gex.net_gex) > 0:
        gamma_concentration = abs(today_gex.net_gex) / abs(full_gex.net_gex) * Decimal("100")
    else:
        gamma_concentration = Decimal("0")

    sorted_pairs = sorted(
        today_gex.per_strike.items(),
        key=lambda kv: abs(kv[1]),
        reverse=True,
    )
    key_strikes = [s for s, _ in sorted_pairs[:3]]

    return ZeroDTEResult(
        timestamp=now,
        bars_used=len(contracts),
        underlying=chain.underlying,
        expiration=today,
        time_to_expiry_hours=to_decimal(hours, ndigits=2),
        pin_risk=pin_risk,
        expected_move=em.expected_move_dollars,
        expected_move_pct=em.expected_move_pct,
        gamma_concentration=gamma_concentration,
        key_strikes=key_strikes,
    )
