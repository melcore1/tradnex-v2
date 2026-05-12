"""Full options analytics aggregator."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, computed_field

from shared.analytics.options.flow import (
    ExpectedMoveResult,
    NetPremiumFlowResult,
    UnusualActivityResult,
    expected_move,
    net_premium_flow,
    unusual_activity,
)
from shared.analytics.options.gex import (
    GEXResult,
    InsufficientChainError,
    gex_by_expiration,
    gex_per_strike,
)
from shared.analytics.options.greeks_aggregation import (
    NetChainGreeksResult,
    SecondOrderGreeksResult,
    net_chain_greeks,
    second_order_greeks,
)
from shared.analytics.options.iv import (
    IVPercentileResult,
    IVRankResult,
    SkewResult,
    TermStructureResult,
    VRPResult,
    iv_percentile,
    iv_rank,
    skew,
    term_structure,
    vrp,
)
from shared.analytics.options.pain import (
    MaxPainResult,
    PCRatioResult,
    max_pain,
    pc_ratio,
)
from shared.analytics.options.zero_dte import ZeroDTEResult, zero_dte_analysis
from shared.analytics.volatility import GARCHResult
from shared.schemas.market import OptionContract, OptionsChain


class FullOptionsAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    spot: Decimal
    timestamp: datetime

    gex: GEXResult
    gex_by_expiration: dict[date, GEXResult]
    second_order_greeks_atm: SecondOrderGreeksResult
    net_chain_greeks: NetChainGreeksResult

    iv_rank: IVRankResult
    iv_percentile: IVPercentileResult
    skew: SkewResult | None
    term_structure: TermStructureResult | None
    vrp: VRPResult | None

    max_pain_per_expiration: dict[date, MaxPainResult]
    pc_ratio: PCRatioResult
    expected_move_per_expiration: dict[date, ExpectedMoveResult]
    unusual_activity: UnusualActivityResult
    net_premium_flow: NetPremiumFlowResult

    zero_dte: ZeroDTEResult | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> str:
        parts = [f"{self.ticker} options"]
        parts.append(f"net GEX {self.gex.net_gex} ({self.gex.regime})")
        if self.gex.call_wall is not None:
            parts.append(f"call wall {self.gex.call_wall}")
        if self.gex.put_wall is not None:
            parts.append(f"put wall {self.gex.put_wall}")
        if self.iv_rank.rank is not None:
            parts.append(
                f"IV rank {self.iv_rank.rank} "
                f"({self.iv_rank.regime if self.iv_rank.regime else 'n/a'})"
            )
        if self.skew is not None:
            parts.append(f"skew {self.skew.regime}")
        front_em = next(iter(self.expected_move_per_expiration.values()), None)
        if front_em is not None:
            parts.append(
                f"expected {front_em.dte}d move ±{front_em.expected_move_pct}%"
            )
        flag_n = len(self.unusual_activity.flagged_contracts)
        parts.append(f"{flag_n} UOA flagged")
        if self.zero_dte is not None:
            parts.append(f"0DTE pin risk {self.zero_dte.pin_risk}")
        return ", ".join(parts)


def _select_current_iv_contract(
    chain: OptionsChain, atm_strike: Decimal
) -> OptionContract:
    """Pick the ATM call whose DTE is in [21, 45] for stable IV-rank input.

    Falls back through progressively broader windows when the preferred range
    is empty (common in 0-14 DTE chains pulled by scout)."""
    calls_at_strike = [
        c
        for c in chain.contracts
        if c.contract_type == "call" and c.strike == atm_strike
    ]
    # Standard window: 21-45 DTE is the industry convention (tastytrade, IBKR) for
    # the "current IV" series stored in daily_iv_snapshots.atm_iv. Picking outside
    # this window (e.g. a 1-DTE row whose annualized IV is 5.0+) breaks IV rank,
    # term-structure scale, and expected-move comparisons against history.
    preferred = [c for c in calls_at_strike if 21 <= c.dte <= 45]
    if preferred:
        return min(preferred, key=lambda c: abs(c.dte - 30))
    # Widen: anything > 14 DTE (skip the 0-DTE / 1-DTE rows whose IV is unusable)
    mid = [c for c in calls_at_strike if c.dte > 14]
    if mid:
        return min(mid, key=lambda c: abs(c.dte - 30))
    # Last resort: existing behaviour (anything > 0 DTE)
    fallback = [c for c in calls_at_strike if c.dte > 0]
    if fallback:
        return min(fallback, key=lambda c: c.dte)
    return chain.contracts[0]


def compute_options_analysis(
    chain: OptionsChain,
    conn: sqlite3.Connection,
    garch_result: GARCHResult | None = None,
    *,
    iv_rank_lookback_days: int = 252,
) -> FullOptionsAnalysis:
    """Run every Tier 3 analytic on a chain. Sequential — pure CPU."""
    spot = chain.spot_at_fetch
    gex_full = gex_per_strike(chain)
    gex_per_exp = gex_by_expiration(chain)

    # ATM front-month contract for second-order Greeks demo
    atm_strike = min({c.strike for c in chain.contracts}, key=lambda s: abs(s - spot))
    atm_call = _select_current_iv_contract(chain, atm_strike)
    second_order = second_order_greeks(atm_call, spot=spot)
    nc = net_chain_greeks(chain)

    current_iv = atm_call.iv
    rank_r = iv_rank(chain.underlying, current_iv, conn, lookback_days=iv_rank_lookback_days)
    pct_r = iv_percentile(chain.underlying, current_iv, conn, lookback_days=iv_rank_lookback_days)

    skew_r: SkewResult | None
    try:
        skew_r = skew(chain)
    except InsufficientChainError:
        skew_r = None

    term_r: TermStructureResult | None
    try:
        term_r = term_structure(chain)
    except InsufficientChainError:
        term_r = None

    vrp_r: VRPResult | None = None
    if garch_result is not None:
        try:
            vrp_r = vrp(chain, garch_result)
        except InsufficientChainError:
            vrp_r = None

    pain_per_exp: dict[date, MaxPainResult] = {}
    em_per_exp: dict[date, ExpectedMoveResult] = {}
    for exp in chain.expirations:
        try:
            pain_per_exp[exp] = max_pain(chain, expiration=exp)
        except InsufficientChainError:
            pass
        try:
            em_per_exp[exp] = expected_move(chain, expiration=exp)
        except InsufficientChainError:
            pass

    pc = pc_ratio(chain)
    uoa = unusual_activity(chain)
    npf = net_premium_flow(chain)
    zdte = zero_dte_analysis(chain)

    return FullOptionsAnalysis(
        ticker=chain.underlying,
        spot=spot,
        timestamp=datetime.now(UTC),
        gex=gex_full,
        gex_by_expiration=gex_per_exp,
        second_order_greeks_atm=second_order,
        net_chain_greeks=nc,
        iv_rank=rank_r,
        iv_percentile=pct_r,
        skew=skew_r,
        term_structure=term_r,
        vrp=vrp_r,
        max_pain_per_expiration=pain_per_exp,
        pc_ratio=pc,
        expected_move_per_expiration=em_per_exp,
        unusual_activity=uoa,
        net_premium_flow=npf,
        zero_dte=zdte,
    )
