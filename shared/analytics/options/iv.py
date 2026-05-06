"""IV analytics: rank, percentile, skew, term structure, VRP."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from shared.analytics.base import IndicatorResult, to_decimal
from shared.analytics.options.gex import InsufficientChainError
from shared.analytics.volatility import GARCHResult
from shared.schemas.market import OptionContract, OptionsChain

IVRegime = Literal["low", "normal", "high"]
SkewRegime = Literal["flat", "normal", "extreme_put_skew", "inverted"]
TermRegime = Literal["contango", "backwardation", "flat"]
VRPRegime = Literal["expensive", "fair", "cheap"]


class IVRankResult(IndicatorResult):
    ticker: str
    current_iv: Decimal
    iv_min_lookback: Decimal | None
    iv_max_lookback: Decimal | None
    rank: Decimal | None
    lookback_days: int
    data_points: int
    regime: IVRegime | None


class IVPercentileResult(IndicatorResult):
    ticker: str
    current_iv: Decimal
    percentile: Decimal | None
    lookback_days: int
    data_points: int


class SkewResult(IndicatorResult):
    underlying: str
    expiration: date
    put_25d_iv: Decimal
    call_25d_iv: Decimal
    skew: Decimal
    regime: SkewRegime


class TermStructureResult(IndicatorResult):
    underlying: str
    points: list[tuple[int, Decimal]]
    front_month_iv: Decimal
    back_month_iv: Decimal
    slope: Decimal
    regime: TermRegime


class VRPResult(IndicatorResult):
    underlying: str
    atm_iv_30d: Decimal
    realized_vol_forecast: Decimal
    vrp: Decimal
    regime: VRPRegime


def _load_iv_history(
    conn: sqlite3.Connection,
    ticker: str,
    lookback_days: int,
) -> list[float]:
    rows = conn.execute(
        "SELECT atm_iv FROM daily_iv_snapshots WHERE ticker = ? "
        "ORDER BY date DESC LIMIT ?",
        (ticker, lookback_days),
    ).fetchall()
    return [float(r[0]) for r in rows if r[0] is not None]


def iv_rank(
    ticker: str,
    current_iv: Decimal,
    conn: sqlite3.Connection,
    lookback_days: int = 252,
    min_data_points: int = 20,
) -> IVRankResult:
    """Current IV relative to (min, max) of historical IV over `lookback_days`."""
    history = _load_iv_history(conn, ticker, lookback_days)
    if len(history) < min_data_points:
        return IVRankResult(
            timestamp=datetime.now(UTC),
            bars_used=0,
            ticker=ticker,
            current_iv=current_iv,
            iv_min_lookback=None,
            iv_max_lookback=None,
            rank=None,
            lookback_days=lookback_days,
            data_points=len(history),
            regime=None,
        )
    iv_min = min(history)
    iv_max = max(history)
    rng = iv_max - iv_min
    rank_val = (
        (float(current_iv) - iv_min) / rng * 100.0 if rng > 0 else 50.0
    )
    rank_val = max(0.0, min(100.0, rank_val))

    if rank_val < 30:
        regime: IVRegime = "low"
    elif rank_val > 70:
        regime = "high"
    else:
        regime = "normal"

    return IVRankResult(
        timestamp=datetime.now(UTC),
        bars_used=0,
        ticker=ticker,
        current_iv=current_iv,
        iv_min_lookback=to_decimal(iv_min),
        iv_max_lookback=to_decimal(iv_max),
        rank=to_decimal(rank_val, ndigits=2),
        lookback_days=lookback_days,
        data_points=len(history),
        regime=regime,
    )


def iv_percentile(
    ticker: str,
    current_iv: Decimal,
    conn: sqlite3.Connection,
    lookback_days: int = 252,
    min_data_points: int = 20,
) -> IVPercentileResult:
    """Percent of historical days when IV was at or below current."""
    history = _load_iv_history(conn, ticker, lookback_days)
    if len(history) < min_data_points:
        return IVPercentileResult(
            timestamp=datetime.now(UTC),
            bars_used=0,
            ticker=ticker,
            current_iv=current_iv,
            percentile=None,
            lookback_days=lookback_days,
            data_points=len(history),
        )
    cur = float(current_iv)
    below = sum(1 for v in history if v <= cur)
    pct = below / len(history) * 100.0
    return IVPercentileResult(
        timestamp=datetime.now(UTC),
        bars_used=0,
        ticker=ticker,
        current_iv=current_iv,
        percentile=to_decimal(pct, ndigits=2),
        lookback_days=lookback_days,
        data_points=len(history),
    )


def _nearest_future_expiration(chain: OptionsChain) -> date:
    today = datetime.now(UTC).date()
    future = [e for e in chain.expirations if e > today]
    if not future:
        # Fall back to anything in the chain (including 0DTE) if no future expiry
        if chain.expirations:
            return chain.expirations[0]
        raise InsufficientChainError("Chain has no expirations")
    return future[0]


def skew(chain: OptionsChain, expiration: date | None = None) -> SkewResult:
    if expiration is None:
        expiration = _nearest_future_expiration(chain)

    contracts = chain.for_expiration(expiration)
    calls = [c for c in contracts if c.contract_type == "call"]
    puts = [c for c in contracts if c.contract_type == "put"]
    if not calls or not puts:
        raise InsufficientChainError(
            f"Need both calls and puts at expiration {expiration}"
        )

    call_25d = min(calls, key=lambda c: abs(float(c.delta) - 0.25))
    put_25d = min(puts, key=lambda c: abs(float(c.delta) - (-0.25)))

    skew_value = put_25d.iv - call_25d.iv

    if skew_value > Decimal("0.05"):
        regime: SkewRegime = "extreme_put_skew"
    elif skew_value > Decimal("0.01"):
        regime = "normal"
    elif skew_value < Decimal("-0.01"):
        regime = "inverted"
    else:
        regime = "flat"

    return SkewResult(
        timestamp=datetime.now(UTC),
        bars_used=len(calls) + len(puts),
        underlying=chain.underlying,
        expiration=expiration,
        put_25d_iv=put_25d.iv,
        call_25d_iv=call_25d.iv,
        skew=skew_value,
        regime=regime,
    )


def term_structure(chain: OptionsChain) -> TermStructureResult:
    if not chain.expirations:
        raise InsufficientChainError("Chain has no expirations")
    spot = chain.spot_at_fetch
    today = datetime.now(UTC).date()

    points: list[tuple[int, Decimal]] = []
    for exp in chain.expirations:
        contracts = chain.for_expiration(exp)
        if not contracts:
            continue
        atm_strike = min({c.strike for c in contracts}, key=lambda s: abs(s - spot))
        same = [c for c in contracts if c.strike == atm_strike]
        if not same:
            continue
        atm_iv = sum((c.iv for c in same), Decimal("0")) / Decimal(len(same))
        dte = (exp - today).days
        points.append((dte, atm_iv))

    if len(points) < 2:
        raise InsufficientChainError(
            f"Term structure needs >= 2 expirations with ATM IV; got {len(points)}"
        )

    points.sort(key=lambda p: p[0])
    front = points[0]
    back = points[-1]
    slope = back[1] - front[1]

    if slope > Decimal("0.005"):
        regime: TermRegime = "contango"
    elif slope < Decimal("-0.005"):
        regime = "backwardation"
    else:
        regime = "flat"

    return TermStructureResult(
        timestamp=datetime.now(UTC),
        bars_used=len(points),
        underlying=chain.underlying,
        points=points,
        front_month_iv=front[1],
        back_month_iv=back[1],
        slope=slope,
        regime=regime,
    )


def vrp(chain: OptionsChain, garch_result: GARCHResult) -> VRPResult:
    """Volatility risk premium: IV - realized vol forecast."""
    if not chain.contracts:
        raise InsufficientChainError("Chain has no contracts")
    spot = chain.spot_at_fetch
    target = 30
    by_dte: dict[int, list[OptionContract]] = {}
    for c in chain.contracts:
        by_dte.setdefault(c.dte, []).append(c)
    if not by_dte:
        raise InsufficientChainError("Chain has no DTE-keyed contracts")
    closest_dte = min(by_dte.keys(), key=lambda d: abs(d - target))
    contracts = by_dte[closest_dte]
    atm_strike = min({c.strike for c in contracts}, key=lambda s: abs(s - spot))
    same = [c for c in contracts if c.strike == atm_strike]
    atm_iv_30d = sum((c.iv for c in same), Decimal("0")) / Decimal(len(same))

    realized = garch_result.annualized_vol_forecast
    vrp_value = atm_iv_30d - realized

    if vrp_value > Decimal("0.05"):
        regime: VRPRegime = "expensive"
    elif vrp_value < Decimal("-0.02"):
        regime = "cheap"
    else:
        regime = "fair"

    return VRPResult(
        timestamp=datetime.now(UTC),
        bars_used=len(same),
        underlying=chain.underlying,
        atm_iv_30d=atm_iv_30d,
        realized_vol_forecast=realized,
        vrp=vrp_value,
        regime=regime,
    )
