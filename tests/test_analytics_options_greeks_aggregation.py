"""Second-order Greeks, portfolio Greeks, net chain Greeks tests.

Reference values: scipy-direct Black-Scholes derivatives. The point of these
tests is that our closed-form formulas match the analytic forms exactly.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from scipy.stats import norm

from shared.analytics import (
    net_chain_greeks,
    portfolio_greeks,
    second_order_greeks,
)
from shared.schemas.core import Position
from shared.schemas.market import OptionContract, OptionsChain

RISK_FREE = 0.05


def _atm_call(
    spot: float = 100.0,
    strike: float = 100.0,
    dte: int = 30,
    iv: float = 0.30,
) -> OptionContract:
    return OptionContract(
        symbol="TEST_ATM",
        underlying="TEST",
        underlying_spot=Decimal(str(spot)),
        expiration=datetime.now(UTC).date() + timedelta(days=dte),
        dte=dte,
        strike=Decimal(str(strike)),
        contract_type="call",
        bid=Decimal("2.50"),
        ask=Decimal("2.60"),
        last=Decimal("2.55"),
        volume=100,
        open_interest=500,
        iv=Decimal(str(iv)),
        delta=Decimal("0.52"),
        gamma=Decimal("0.04"),
        theta=Decimal("-0.05"),
        vega=Decimal("0.15"),
        rho=Decimal("0.08"),
    )


def _bs_d1_d2(s: float, k: float, dte: int, iv: float) -> tuple[float, float, float]:
    T = dte / 365.0
    sqrt_T = float(np.sqrt(T))
    d1 = (float(np.log(s / k)) + (RISK_FREE + 0.5 * iv * iv) * T) / (iv * sqrt_T)
    d2 = d1 - iv * sqrt_T
    return d1, d2, sqrt_T


def test_vanna_matches_analytic_value() -> None:
    contract = _atm_call()
    result = second_order_greeks(contract)

    # Analytic vanna per 1% IV change
    s, k, dte, iv = 100.0, 100.0, 30, 0.30
    d1, d2, _ = _bs_d1_d2(s, k, dte, iv)
    expected = -float(norm.pdf(d1)) * d2 / iv / 100.0

    assert abs(float(result.vanna) - expected) < 1e-6


def test_vomma_matches_analytic_value() -> None:
    contract = _atm_call()
    result = second_order_greeks(contract)

    s, k, dte, iv = 100.0, 100.0, 30, 0.30
    d1, d2, sqrt_T = _bs_d1_d2(s, k, dte, iv)
    pdf_d1 = float(norm.pdf(d1))
    vega_per_pct = (s * pdf_d1 * sqrt_T) / 100.0
    expected = vega_per_pct * d1 * d2 / iv

    assert abs(float(result.vomma) - expected) < 1e-6


def test_charm_matches_analytic_value() -> None:
    contract = _atm_call()
    result = second_order_greeks(contract)

    s, k, dte, iv = 100.0, 100.0, 30, 0.30
    T = dte / 365.0
    d1, d2, sqrt_T = _bs_d1_d2(s, k, dte, iv)
    pdf_d1 = float(norm.pdf(d1))
    charm_year = -pdf_d1 * (2 * RISK_FREE * T - d2 * iv * sqrt_T) / (2 * T * iv * sqrt_T)
    expected = charm_year / 365.0

    assert abs(float(result.charm) - expected) < 1e-6


def test_speed_matches_analytic_value() -> None:
    contract = _atm_call()
    result = second_order_greeks(contract)

    s, k, dte, iv = 100.0, 100.0, 30, 0.30
    d1, _, sqrt_T = _bs_d1_d2(s, k, dte, iv)
    pdf_d1 = float(norm.pdf(d1))
    gamma = pdf_d1 / (s * iv * sqrt_T)
    expected = -gamma / s * (d1 / (iv * sqrt_T) + 1.0)

    assert abs(float(result.speed) - expected) < 1e-7


def test_second_order_greeks_zero_for_expired() -> None:
    contract = _atm_call(dte=0)
    result = second_order_greeks(contract)
    assert result.vanna == Decimal("0")
    assert result.charm == Decimal("0")
    assert result.vomma == Decimal("0")
    assert result.speed == Decimal("0")


def test_net_chain_greeks_aggregates_with_oi_weight() -> None:
    c1 = _atm_call()
    chain = OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal("100"),
        contracts=[c1],
        timestamp=datetime.now(UTC),
    )
    result = net_chain_greeks(chain)
    # delta * OI * 100 = 0.52 * 500 * 100 = 26000
    assert float(result.net_chain_delta) == pytest.approx(26000, rel=1e-4)


def test_portfolio_greeks_long_position_signs() -> None:
    contract = _atm_call()
    pos = Position(
        ticker="TEST",
        contract_symbol=contract.symbol,
        side="long",
        quantity=10,
        entry_price=Decimal("2.55"),
        entry_ts=0.0,
        status="open",
    )
    result = portfolio_greeks([pos], {contract.symbol: contract}, spot=Decimal("100"))
    # delta * qty * 100 = 0.52 * 10 * 100 = 520
    assert float(result.net_delta) == pytest.approx(520, rel=1e-4)
    assert result.positions_count == 1


def test_portfolio_greeks_short_position_inverts() -> None:
    contract = _atm_call()
    pos = Position(
        ticker="TEST",
        contract_symbol=contract.symbol,
        side="short",
        quantity=10,
        entry_price=Decimal("2.55"),
        entry_ts=0.0,
        status="open",
    )
    result = portfolio_greeks([pos], {contract.symbol: contract}, spot=Decimal("100"))
    assert float(result.net_delta) == pytest.approx(-520, rel=1e-4)


def test_portfolio_greeks_skips_closed_positions() -> None:
    contract = _atm_call()
    pos = Position(
        ticker="TEST",
        contract_symbol=contract.symbol,
        side="long",
        quantity=10,
        entry_price=Decimal("2.55"),
        entry_ts=0.0,
        status="closed",
    )
    result = portfolio_greeks([pos], {contract.symbol: contract}, spot=Decimal("100"))
    assert result.net_delta == Decimal("0")
    assert result.positions_count == 0
