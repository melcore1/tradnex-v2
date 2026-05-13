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

    # Nullable: when the chain contains no call contracts with DTE > 14 (e.g.
    # an after-hours scout pulled an expiry-day-only chain), the IV selector
    # raises and these go null rather than emitting a 0DTE 500%+ reading.
    iv_rank: IVRankResult | None
    iv_percentile: IVPercentileResult | None
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
        if self.iv_rank is not None and self.iv_rank.rank is not None:
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


def _select_current_iv_contract(chain: OptionsChain) -> OptionContract:
    """Pick a call contract whose IV is a stable input to IV rank / term structure.

    Preference: closest expiry to 30 DTE in the [21, 45] window, then closest
    strike to spot within that expiry. Widens to (14, ∞) DTE only if the
    preferred window is empty. Picks ATM **per expiry** rather than at a
    chain-wide global strike — longer expiries have wider strike spacing, so
    the global ATM strike often doesn't exist there and the previous selector
    silently fell back to a 1-DTE row whose annualized IV reads as 500%+.

    Raises:
        InsufficientChainError: when no call contract with DTE > 14 exists
            (e.g. chain only contains 0-DTE / 1-DTE pinning rows).
    """
    spot = chain.spot_at_fetch
    calls = [c for c in chain.contracts if c.contract_type == "call"]
    if not calls:
        raise InsufficientChainError("Chain has no call contracts for IV selection")

    preferred = [c for c in calls if 21 <= c.dte <= 45]
    pool = preferred or [c for c in calls if c.dte > 14]
    if not pool:
        raise InsufficientChainError(
            "No call contracts with DTE > 14 for stable current-IV selection"
        )
    target_dte = min({c.dte for c in pool}, key=lambda d: abs(d - 30))
    in_expiry = [c for c in pool if c.dte == target_dte]
    return min(in_expiry, key=lambda c: abs(c.strike - spot))


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
    nc = net_chain_greeks(chain)

    # Second-order Greeks pinned to whichever call is closest to spot in the
    # chain; falls back to first contract if no calls exist. The IV-rank
    # selection is stricter (>14 DTE only) and lives separately below.
    if chain.contracts:
        atm_for_greeks = min(chain.contracts, key=lambda c: abs(c.strike - spot))
    else:
        atm_for_greeks = chain.contracts[0]
    second_order = second_order_greeks(atm_for_greeks, spot=spot)

    rank_r: IVRankResult | None
    pct_r: IVPercentileResult | None
    try:
        atm_call = _select_current_iv_contract(chain)
        current_iv = atm_call.iv
        rank_r = iv_rank(
            chain.underlying, current_iv, conn, lookback_days=iv_rank_lookback_days
        )
        pct_r = iv_percentile(
            chain.underlying, current_iv, conn, lookback_days=iv_rank_lookback_days
        )
    except InsufficientChainError:
        rank_r = None
        pct_r = None

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
