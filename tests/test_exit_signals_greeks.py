"""Greek-based exit signals."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from shared.schemas.core import Position
from shared.schemas.market import OptionContract
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import ExitSignalSeverity
from shared.strategy.exit_signals.greeks import (
    signal_charm_acceleration,
    signal_delta_too_high,
    signal_delta_too_low,
    signal_theta_acceleration,
    signal_vega_exposure,
)


def _pos(qty: int = 1, entry: Decimal = Decimal("2.50")) -> Position:
    return Position(
        id=1,
        ticker="NVDA",
        contract_symbol="NVDA260515C00145000",
        side="long",
        quantity=qty,
        entry_price=entry,
        entry_ts=0.0,
        status="open",
    )


def _contract(
    *,
    delta: Decimal = Decimal("0.30"),
    theta: Decimal = Decimal("-0.05"),
    vega: Decimal = Decimal("0.10"),
    gamma: Decimal = Decimal("0.05"),
    bid: Decimal = Decimal("2.40"),
    ask: Decimal = Decimal("2.50"),
    dte: int = 9,
) -> OptionContract:
    today = datetime.now(UTC).date()
    return OptionContract(
        symbol="NVDA260515C00145000",
        underlying="NVDA",
        underlying_spot=Decimal("145"),
        expiration=today + timedelta(days=dte),
        dte=dte,
        strike=Decimal("145"),
        contract_type="call",
        bid=bid,
        ask=ask,
        last=(bid + ask) / 2,
        volume=500,
        open_interest=5000,
        iv=Decimal("0.32"),
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        rho=Decimal("0.01"),
    )


def test_delta_too_high_urgent() -> None:
    result = signal_delta_too_high(_pos(), _contract(delta=Decimal("0.75")), ExitSettings())
    assert result.severity == ExitSignalSeverity.URGENT
    assert result.triggered


def test_delta_too_low_urgent() -> None:
    result = signal_delta_too_low(_pos(), _contract(delta=Decimal("0.08")), ExitSettings())
    assert result.severity == ExitSignalSeverity.URGENT
    assert result.triggered


def test_theta_acceleration_urgent() -> None:
    # 1 contract, mid=2.45, notional=245, theta=-0.20 ($20/day) → 8.16% / day
    contract = _contract(theta=Decimal("-0.20"), bid=Decimal("2.40"), ask=Decimal("2.50"))
    result = signal_theta_acceleration(_pos(qty=1), contract, ExitSettings())
    assert result.severity == ExitSignalSeverity.URGENT
    assert result.triggered


def test_vega_exposure_info_in_normal_range() -> None:
    contract = _contract(vega=Decimal("0.05"))
    result = signal_vega_exposure(_pos(), contract, ExitSettings())
    assert result.severity == ExitSignalSeverity.INFO


def test_vega_exposure_warning_when_high() -> None:
    # Big vega → exposure > 10% of notional
    contract = _contract(vega=Decimal("0.50"), bid=Decimal("2.40"), ask=Decimal("2.50"))
    result = signal_vega_exposure(_pos(), contract, ExitSettings())
    assert result.severity == ExitSignalSeverity.WARNING
    assert result.triggered


def test_charm_always_info() -> None:
    result = signal_charm_acceleration(
        _pos(), _contract(dte=2, gamma=Decimal("0.10")), ExitSettings()
    )
    assert result.severity == ExitSignalSeverity.INFO
    assert not result.triggered  # charm is informational only
