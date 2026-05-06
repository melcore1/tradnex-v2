"""Max pain and put/call ratios."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from shared.analytics.base import IndicatorResult
from shared.analytics.options.gex import InsufficientChainError
from shared.schemas.market import OptionsChain

PainRegime = Literal["pinning", "near_max_pain", "far_from"]
PCRegime = Literal["bullish", "neutral", "bearish"]


class MaxPainResult(IndicatorResult):
    underlying: str
    expiration: date
    max_pain_strike: Decimal
    current_spot: Decimal
    distance_pct: Decimal
    regime: PainRegime


class PCRatioResult(IndicatorResult):
    underlying: str
    oi_pc_ratio: Decimal
    volume_pc_ratio: Decimal
    regime_oi: PCRegime
    regime_volume: PCRegime


def max_pain(chain: OptionsChain, expiration: date | None = None) -> MaxPainResult:
    if expiration is None:
        today = datetime.now(UTC).date()
        future = [e for e in chain.expirations if e >= today]
        if not future:
            if not chain.expirations:
                raise InsufficientChainError("Chain has no expirations")
            expiration = chain.expirations[0]
        else:
            expiration = future[0]

    contracts = chain.for_expiration(expiration)
    if not contracts:
        raise InsufficientChainError(f"No contracts for expiration {expiration}")

    candidate_strikes = sorted({c.strike for c in contracts})
    if not candidate_strikes:
        raise InsufficientChainError("No strikes")

    pain_per_strike: dict[Decimal, Decimal] = {}
    zero = Decimal("0")
    for K in candidate_strikes:
        total = zero
        for c in contracts:
            oi = Decimal(c.open_interest)
            if c.contract_type == "call":
                if c.strike < K:
                    total += (K - c.strike) * oi
            else:
                if c.strike > K:
                    total += (c.strike - K) * oi
        pain_per_strike[K] = total

    # Max pain = strike that MINIMIZES total intrinsic payout (writers benefit most).
    max_pain_strike = min(pain_per_strike.items(), key=lambda kv: kv[1])[0]

    spot = chain.spot_at_fetch
    distance_pct = (
        (abs(spot - max_pain_strike) / spot * Decimal("100")).quantize(Decimal("0.0001"))
        if spot > 0
        else zero
    )

    if distance_pct < Decimal("0.5"):
        regime: PainRegime = "pinning"
    elif distance_pct < Decimal("2"):
        regime = "near_max_pain"
    else:
        regime = "far_from"

    return MaxPainResult(
        timestamp=datetime.now(UTC),
        bars_used=len(contracts),
        underlying=chain.underlying,
        expiration=expiration,
        max_pain_strike=max_pain_strike,
        current_spot=spot,
        distance_pct=distance_pct,
        regime=regime,
    )


def pc_ratio(chain: OptionsChain) -> PCRatioResult:
    if not chain.contracts:
        raise InsufficientChainError("Chain has no contracts")

    call_oi = 0
    put_oi = 0
    call_vol = 0
    put_vol = 0
    for c in chain.contracts:
        if c.contract_type == "call":
            call_oi += c.open_interest
            call_vol += c.volume
        else:
            put_oi += c.open_interest
            put_vol += c.volume

    oi_ratio = (
        (Decimal(put_oi) / Decimal(call_oi)).quantize(Decimal("0.0001"))
        if call_oi > 0
        else Decimal("0")
    )
    vol_ratio = (
        (Decimal(put_vol) / Decimal(call_vol)).quantize(Decimal("0.0001"))
        if call_vol > 0
        else Decimal("0")
    )

    def classify(r: Decimal) -> PCRegime:
        if r > Decimal("1.2"):
            return "bearish"
        if r < Decimal("0.7"):
            return "bullish"
        return "neutral"

    return PCRatioResult(
        timestamp=datetime.now(UTC),
        bars_used=len(chain.contracts),
        underlying=chain.underlying,
        oi_pc_ratio=oi_ratio,
        volume_pc_ratio=vol_ratio,
        regime_oi=classify(oi_ratio),
        regime_volume=classify(vol_ratio),
    )
