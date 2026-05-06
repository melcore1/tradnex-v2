"""Flow analytics: expected move, unusual activity, net premium flow."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from shared.analytics.base import IndicatorResult
from shared.analytics.options.gex import InsufficientChainError
from shared.schemas.market import ContractType, OptionsChain

FlowDirection = Literal["bullish", "bearish", "neutral"]


class ExpectedMoveResult(IndicatorResult):
    underlying: str
    expiration: date
    dte: int
    atm_strike: Decimal
    straddle_price: Decimal
    expected_move_dollars: Decimal
    expected_move_pct: Decimal
    upside_target: Decimal
    downside_target: Decimal


class FlaggedContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    type: ContractType
    strike: Decimal
    expiration: date
    volume: int
    open_interest: int
    ratio: Decimal
    classification: FlowDirection
    premium_dollars: Decimal


class UnusualActivityResult(IndicatorResult):
    underlying: str
    flagged_contracts: list[FlaggedContract]
    bullish_flow_dollars: Decimal
    bearish_flow_dollars: Decimal
    net_flow_direction: FlowDirection


class NetPremiumFlowResult(IndicatorResult):
    underlying: str
    total_call_premium: Decimal
    total_put_premium: Decimal
    net_premium: Decimal
    direction: FlowDirection


def expected_move(chain: OptionsChain, expiration: date | None = None) -> ExpectedMoveResult:
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
    calls = [c for c in contracts if c.contract_type == "call"]
    puts = [c for c in contracts if c.contract_type == "put"]
    if not calls or not puts:
        raise InsufficientChainError(
            f"expected_move needs both calls and puts at {expiration}"
        )

    spot = chain.spot_at_fetch
    atm_strike = min({c.strike for c in contracts}, key=lambda s: abs(s - spot))
    atm_calls = [c for c in calls if c.strike == atm_strike]
    atm_puts = [c for c in puts if c.strike == atm_strike]
    if not atm_calls or not atm_puts:
        raise InsufficientChainError(f"No ATM call/put at {atm_strike} {expiration}")

    atm_call = atm_calls[0]
    atm_put = atm_puts[0]
    straddle = (atm_call.mid + atm_put.mid).quantize(Decimal("0.0001"))
    em_pct = (
        (straddle / spot * Decimal("100")).quantize(Decimal("0.0001"))
        if spot > 0
        else Decimal("0")
    )
    today = datetime.now(UTC).date()
    dte = (expiration - today).days

    return ExpectedMoveResult(
        timestamp=datetime.now(UTC),
        bars_used=len(contracts),
        underlying=chain.underlying,
        expiration=expiration,
        dte=dte,
        atm_strike=atm_strike,
        straddle_price=straddle,
        expected_move_dollars=straddle,
        expected_move_pct=em_pct,
        upside_target=spot + straddle,
        downside_target=spot - straddle,
    )


def unusual_activity(
    chain: OptionsChain,
    vol_oi_threshold: float = 2.0,
) -> UnusualActivityResult:
    """Heuristic UOA: flag contracts with volume/OI > threshold.

    Without trade-by-trade data we can't tell aggressor side reliably; we
    classify by contract_type as a coarse proxy (calls bullish, puts bearish).
    A future enhancement could pull tape data for higher fidelity.
    """
    flagged: list[FlaggedContract] = []
    bullish_dollars = Decimal("0")
    bearish_dollars = Decimal("0")
    for c in chain.contracts:
        if c.open_interest <= 0:
            continue
        ratio = c.volume / c.open_interest
        if ratio < vol_oi_threshold:
            continue
        classification: FlowDirection = (
            "bullish" if c.contract_type == "call" else "bearish"
        )
        premium = c.mid * Decimal(c.volume) * Decimal("100")
        flagged.append(
            FlaggedContract(
                symbol=c.symbol,
                type=c.contract_type,
                strike=c.strike,
                expiration=c.expiration,
                volume=c.volume,
                open_interest=c.open_interest,
                ratio=Decimal(str(round(ratio, 4))),
                classification=classification,
                premium_dollars=premium,
            )
        )
        if classification == "bullish":
            bullish_dollars += premium
        else:
            bearish_dollars += premium

    if bullish_dollars > bearish_dollars * Decimal("1.2"):
        direction: FlowDirection = "bullish"
    elif bearish_dollars > bullish_dollars * Decimal("1.2"):
        direction = "bearish"
    else:
        direction = "neutral"

    return UnusualActivityResult(
        timestamp=datetime.now(UTC),
        bars_used=len(chain.contracts),
        underlying=chain.underlying,
        flagged_contracts=flagged,
        bullish_flow_dollars=bullish_dollars,
        bearish_flow_dollars=bearish_dollars,
        net_flow_direction=direction,
    )


def net_premium_flow(chain: OptionsChain) -> NetPremiumFlowResult:
    if not chain.contracts:
        raise InsufficientChainError("Chain has no contracts")
    call_total = Decimal("0")
    put_total = Decimal("0")
    for c in chain.contracts:
        premium = c.mid * Decimal(c.volume) * Decimal("100")
        if c.contract_type == "call":
            call_total += premium
        else:
            put_total += premium

    net = call_total - put_total
    total = call_total + put_total
    threshold = total * Decimal("0.10")
    if net > threshold:
        direction: FlowDirection = "bullish"
    elif -net > threshold:
        direction = "bearish"
    else:
        direction = "neutral"

    return NetPremiumFlowResult(
        timestamp=datetime.now(UTC),
        bars_used=len(chain.contracts),
        underlying=chain.underlying,
        total_call_premium=call_total,
        total_put_premium=put_total,
        net_premium=net,
        direction=direction,
    )
