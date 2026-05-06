"""Greeks aggregation: second-order Greeks, portfolio Greeks, net chain Greeks.

Closed-form Black-Scholes derivatives via scipy.stats.norm. Assumes a
non-dividend-paying stock; charm picks up an extra ±q·N(±d1) term for
dividend-paying assets which we omit here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
from pydantic import ConfigDict
from scipy.stats import norm

from shared.analytics.base import IndicatorResult, to_decimal
from shared.schemas.core import Position
from shared.schemas.market import OptionContract, OptionsChain

RISK_FREE_RATE = 0.05


class SecondOrderGreeksResult(IndicatorResult):
    symbol: str
    spot: Decimal
    strike: Decimal
    iv: Decimal
    dte: int
    contract_type: str
    vanna: Decimal
    charm: Decimal  # per day, consistent with theta convention
    vomma: Decimal
    speed: Decimal


class NetChainGreeksResult(IndicatorResult):
    underlying: str
    net_chain_delta: Decimal
    net_chain_gamma: Decimal
    net_chain_vega: Decimal
    net_chain_theta: Decimal


class PortfolioGreeksResult(IndicatorResult):
    model_config = ConfigDict(frozen=True)

    spot: Decimal
    net_delta: Decimal
    net_gamma: Decimal
    net_theta: Decimal
    net_vega: Decimal
    net_rho: Decimal
    dollar_delta: Decimal
    dollar_gamma: Decimal
    concentration_warnings: list[str]
    positions_count: int


def _bs_d1_d2(spot: float, strike: float, dte: int, iv: float) -> tuple[float, float]:
    T = dte / 365.0
    sqrt_T = float(np.sqrt(T))
    d1 = (float(np.log(spot / strike)) + (RISK_FREE_RATE + 0.5 * iv * iv) * T) / (iv * sqrt_T)
    d2 = d1 - iv * sqrt_T
    return d1, d2


def second_order_greeks(
    contract: OptionContract,
    spot: Decimal | None = None,
) -> SecondOrderGreeksResult:
    """Vanna, charm (per day), vomma, speed for a single contract.

    Vanna is reported per 1% IV change (i.e. ∂Δ ÷ ∂σ × 0.01).
    Vomma is reported per 1% IV change (consistent with our vega convention).
    Charm is per day (theta-style).
    Speed is ∂Γ/∂S in the natural unit (Γ change per $1 spot move).
    """
    spot_val = float(spot if spot is not None else contract.underlying_spot)
    strike_f = float(contract.strike)
    iv_f = float(contract.iv)
    dte = max(contract.dte, 0)

    if dte <= 0 or iv_f <= 0 or spot_val <= 0:
        zero = to_decimal(0.0)
        return SecondOrderGreeksResult(
            timestamp=datetime.now(UTC),
            bars_used=0,
            symbol=contract.symbol,
            spot=to_decimal(spot_val),
            strike=contract.strike,
            iv=contract.iv,
            dte=dte,
            contract_type=contract.contract_type,
            vanna=zero,
            charm=zero,
            vomma=zero,
            speed=zero,
        )

    T = dte / 365.0
    sqrt_T = float(np.sqrt(T))
    d1, d2 = _bs_d1_d2(spot_val, strike_f, dte, iv_f)
    pdf_d1 = float(norm.pdf(d1))
    gamma = pdf_d1 / (spot_val * iv_f * sqrt_T)
    vega_unit = spot_val * pdf_d1 * sqrt_T  # per 1.0 IV change
    vega_per_pct = vega_unit / 100.0

    # Vanna: ∂Δ/∂σ (per 1.0 σ); convert to per 1%
    vanna_unit = -pdf_d1 * d2 / iv_f
    vanna_per_pct = vanna_unit / 100.0

    # Vomma: ∂vega/∂σ — keep consistent units with vega (per 1%)
    vomma_per_pct = vega_per_pct * d1 * d2 / iv_f

    # Charm (per year, no-div). Same magnitude for call/put with q=0.
    charm_per_year = -pdf_d1 * (2 * RISK_FREE_RATE * T - d2 * iv_f * sqrt_T) / (
        2 * T * iv_f * sqrt_T
    )
    charm_per_day = charm_per_year / 365.0

    # Speed: ∂Γ/∂S
    speed = -gamma / spot_val * (d1 / (iv_f * sqrt_T) + 1.0)

    return SecondOrderGreeksResult(
        timestamp=datetime.now(UTC),
        bars_used=0,
        symbol=contract.symbol,
        spot=to_decimal(spot_val),
        strike=contract.strike,
        iv=contract.iv,
        dte=dte,
        contract_type=contract.contract_type,
        vanna=to_decimal(vanna_per_pct, ndigits=6),
        charm=to_decimal(charm_per_day, ndigits=6),
        vomma=to_decimal(vomma_per_pct, ndigits=6),
        speed=to_decimal(speed, ndigits=8),
    )


def net_chain_greeks(chain: OptionsChain) -> NetChainGreeksResult:
    """Aggregate Greeks across the full chain weighted by OI × 100 (contract multiplier)."""
    delta = Decimal("0")
    gamma = Decimal("0")
    vega = Decimal("0")
    theta = Decimal("0")
    for c in chain.contracts:
        weight = Decimal(c.open_interest) * Decimal("100")
        delta += c.delta * weight
        gamma += c.gamma * weight
        vega += c.vega * weight
        theta += c.theta * weight
    return NetChainGreeksResult(
        timestamp=datetime.now(UTC),
        bars_used=0,
        underlying=chain.underlying,
        net_chain_delta=delta,
        net_chain_gamma=gamma,
        net_chain_vega=vega,
        net_chain_theta=theta,
    )


def portfolio_greeks(
    positions: list[Position],
    chain_lookup: dict[str, OptionContract],
    spot: Decimal,
    *,
    delta_dollar_warn: Decimal = Decimal("100000"),
    theta_dollar_warn: Decimal = Decimal("500"),
    vega_dollar_warn: Decimal = Decimal("1000"),
) -> PortfolioGreeksResult:
    """Sum Greeks across open positions. side = long/short maps to ±sign."""
    net_delta = Decimal("0")
    net_gamma = Decimal("0")
    net_theta = Decimal("0")
    net_vega = Decimal("0")
    net_rho = Decimal("0")

    for pos in positions:
        if pos.status != "open":
            continue
        contract = chain_lookup.get(pos.contract_symbol)
        if contract is None:
            continue
        sign = Decimal("1") if pos.side == "long" else Decimal("-1")
        weight = sign * Decimal(pos.quantity) * Decimal("100")
        net_delta += contract.delta * weight
        net_gamma += contract.gamma * weight
        net_theta += contract.theta * weight
        net_vega += contract.vega * weight
        net_rho += contract.rho * weight

    dollar_delta = net_delta * spot
    dollar_gamma = net_gamma * spot * spot * Decimal("0.01")  # per 1% spot move

    warnings: list[str] = []
    if abs(dollar_delta) > delta_dollar_warn:
        warnings.append(f"|dollar delta| ${abs(dollar_delta)} exceeds ${delta_dollar_warn}")
    if abs(net_theta) > theta_dollar_warn:
        warnings.append(f"|net theta| ${abs(net_theta)}/day exceeds ${theta_dollar_warn}/day")
    if abs(net_vega) > vega_dollar_warn:
        warnings.append(f"|net vega| ${abs(net_vega)} exceeds ${vega_dollar_warn}")

    return PortfolioGreeksResult(
        timestamp=datetime.now(UTC),
        bars_used=0,
        spot=spot,
        net_delta=net_delta,
        net_gamma=net_gamma,
        net_theta=net_theta,
        net_vega=net_vega,
        net_rho=net_rho,
        dollar_delta=dollar_delta,
        dollar_gamma=dollar_gamma,
        concentration_warnings=warnings,
        positions_count=sum(1 for p in positions if p.status == "open"),
    )
