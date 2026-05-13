"""Gamma exposure (GEX) — SpotGamma convention: calls positive, puts negative.

GEX_strike = sum_over_contracts(sign * gamma * OI * 100 * spot² * 0.01)

Net positive GEX → dealers long gamma → mean-reverting / stable regime.
Net negative GEX → dealers short gamma → momentum / volatile regime.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import computed_field

from shared.analytics.base import IndicatorResult, to_decimal
from shared.schemas.market import OptionsChain

GEXRegime = Literal["positive_gamma", "negative_gamma", "flip_zone"]
DealerPosition = Literal["long_gamma", "short_gamma", "neutral"]


class InsufficientChainError(ValueError):
    """Raised when an options-analytics call gets a chain that can't satisfy the computation."""


class GEXResult(IndicatorResult):
    underlying: str
    spot: Decimal
    per_strike: dict[Decimal, Decimal]
    net_gex: Decimal
    regime: GEXRegime
    gamma_flip: Decimal | None
    call_wall: Decimal | None
    put_wall: Decimal | None
    dealer_position: DealerPosition

    @computed_field  # type: ignore[prop-decorator]
    @property
    def distance_to_flip_pct(self) -> Decimal | None:
        if self.gamma_flip is None or self.spot == 0:
            return None
        return (self.gamma_flip - self.spot) / self.spot * Decimal("100")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def distance_to_call_wall_pct(self) -> Decimal | None:
        if self.call_wall is None or self.spot == 0:
            return None
        return (self.call_wall - self.spot) / self.spot * Decimal("100")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def distance_to_put_wall_pct(self) -> Decimal | None:
        if self.put_wall is None or self.spot == 0:
            return None
        return (self.put_wall - self.spot) / self.spot * Decimal("100")


def gex_per_strike(
    chain: OptionsChain,
    expiration: date | None = None,
) -> GEXResult:
    # TODO: Validate against published SpotGamma SPY levels once
    # Schwab data flows. Goal: our net GEX should match within ~5%.
    # If signs are flipped or magnitudes off, revisit the sign
    # convention or the formula coefficient.
    if not chain.contracts:
        raise InsufficientChainError("Chain has no contracts")

    contracts = chain.contracts
    if expiration is not None:
        contracts = [c for c in contracts if c.expiration == expiration]
    if not contracts:
        raise InsufficientChainError(f"No contracts for expiration {expiration}")

    spot = chain.spot_at_fetch
    spot_f = float(spot)
    spot_sq = spot_f * spot_f

    per_strike_f: dict[Decimal, float] = {}
    for c in contracts:
        sign = 1.0 if c.contract_type == "call" else -1.0
        contribution = (
            sign * float(c.gamma) * c.open_interest * 100.0 * spot_sq * 0.01
        )
        per_strike_f[c.strike] = per_strike_f.get(c.strike, 0.0) + contribution

    net_gex_f = sum(per_strike_f.values())
    total_abs = sum(abs(v) for v in per_strike_f.values())

    # Walls
    call_wall: Decimal | None = None
    put_wall: Decimal | None = None
    if per_strike_f:
        positives = {k: v for k, v in per_strike_f.items() if v > 0}
        negatives = {k: v for k, v in per_strike_f.items() if v < 0}
        if positives:
            call_wall = max(positives.items(), key=lambda kv: kv[1])[0]
        if negatives:
            put_wall = min(negatives.items(), key=lambda kv: kv[1])[0]

    # Gamma flip: sweep strikes ascending, find sign change in cumulative GEX
    sorted_strikes = sorted(per_strike_f.keys())
    cumulative = 0.0
    gamma_flip: Decimal | None = None
    for strike in sorted_strikes:
        prev = cumulative
        cumulative += per_strike_f[strike]
        if (prev <= 0 < cumulative) or (prev >= 0 > cumulative):
            gamma_flip = strike
            break

    if total_abs == 0:
        # Degenerate chain (no gamma contributions — e.g. after-hours when all
        # contracts have gamma=0 and open_interest=0). Don't fabricate a
        # directional regime — the dealer is structurally neutral.
        regime: GEXRegime = "flip_zone"
    elif abs(net_gex_f) < 0.01 * total_abs:
        regime = "flip_zone"
    elif net_gex_f > 0:
        regime = "positive_gamma"
    else:
        regime = "negative_gamma"

    if abs(net_gex_f) < 1e-6:
        dealer_position: DealerPosition = "neutral"
    elif net_gex_f > 0:
        dealer_position = "long_gamma"
    else:
        dealer_position = "short_gamma"

    return GEXResult(
        timestamp=datetime.now(UTC),
        bars_used=len(contracts),
        underlying=chain.underlying,
        spot=spot,
        per_strike={k: to_decimal(v, ndigits=2) for k, v in per_strike_f.items()},
        net_gex=to_decimal(net_gex_f, ndigits=2),
        regime=regime,
        gamma_flip=gamma_flip,
        call_wall=call_wall,
        put_wall=put_wall,
        dealer_position=dealer_position,
    )


def gex_by_expiration(chain: OptionsChain) -> dict[date, GEXResult]:
    """Per-expiration GEX. Useful for spotting which expiry drives the dealer book."""
    if not chain.contracts:
        raise InsufficientChainError("Chain has no contracts")
    out: dict[date, GEXResult] = {}
    for exp in chain.expirations:
        try:
            out[exp] = gex_per_strike(chain, expiration=exp)
        except InsufficientChainError:
            continue
    return out


# Re-export the analytics-specific exception under a friendly name
__all__ = [
    "GEXResult",
    "GEXRegime",
    "DealerPosition",
    "InsufficientChainError",
    "gex_per_strike",
    "gex_by_expiration",
]
