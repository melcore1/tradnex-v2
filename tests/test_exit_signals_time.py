"""Time-based exit signals."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from shared.schemas.core import Position
from shared.schemas.market import OptionContract
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import ExitSignalSeverity
from shared.strategy.exit_signals.time import (
    signal_dte_critical,
    signal_friday_position_short_dte,
)

ET = ZoneInfo("America/New_York")


def _pos() -> Position:
    return Position(
        id=1, ticker="NVDA", contract_symbol="X", side="long", quantity=1,
        entry_price=Decimal("2.50"), entry_ts=0.0, status="open",
    )


def _contract(dte: int) -> OptionContract:
    today = datetime.now(UTC).date()
    return OptionContract(
        symbol="X", underlying="NVDA", underlying_spot=Decimal("145"),
        expiration=today + timedelta(days=max(dte, 0)),
        dte=dte, strike=Decimal("145"), contract_type="call",
        bid=Decimal("1.0"), ask=Decimal("1.1"), last=Decimal("1.05"),
        volume=100, open_interest=1000, iv=Decimal("0.30"),
        delta=Decimal("0.30"), gamma=Decimal("0.05"), theta=Decimal("-0.05"),
        vega=Decimal("0.10"), rho=Decimal("0.01"),
    )


def test_dte_zero_urgent() -> None:
    now = datetime.now(ET).replace(hour=15, minute=0)
    result = signal_dte_critical(_pos(), _contract(dte=0), now, ExitSettings())
    assert result.severity == ExitSignalSeverity.URGENT
    assert result.triggered


def test_dte_one_afternoon_urgent() -> None:
    # ET 14:00 with DTE=1 → URGENT
    now = datetime.now(UTC).replace(year=2026, month=5, day=4, hour=18, minute=0)
    result = signal_dte_critical(_pos(), _contract(dte=1), now, ExitSettings())
    assert result.severity == ExitSignalSeverity.URGENT
    assert result.triggered


def test_dte_two_warning() -> None:
    now = datetime.now(UTC).replace(year=2026, month=5, day=4, hour=18, minute=0)
    result = signal_dte_critical(_pos(), _contract(dte=2), now, ExitSettings())
    assert result.severity == ExitSignalSeverity.WARNING
    assert result.triggered


def test_dte_ten_info_not_triggered() -> None:
    now = datetime.now(UTC).replace(year=2026, month=5, day=4, hour=18, minute=0)
    result = signal_dte_critical(_pos(), _contract(dte=10), now, ExitSettings())
    assert result.severity == ExitSignalSeverity.INFO
    assert not result.triggered


def test_friday_short_dte_warning() -> None:
    # Friday May 8 2026, 14:00 ET = 18:00 UTC
    friday_afternoon = datetime(2026, 5, 8, 18, 0, tzinfo=UTC)
    result = signal_friday_position_short_dte(
        _pos(), _contract(dte=4), friday_afternoon, ExitSettings()
    )
    assert result.severity == ExitSignalSeverity.WARNING
    assert result.triggered

    # Same DTE but on a Tuesday → INFO not triggered
    tuesday = datetime(2026, 5, 5, 18, 0, tzinfo=UTC)
    result2 = signal_friday_position_short_dte(
        _pos(), _contract(dte=4), tuesday, ExitSettings()
    )
    assert result2.severity == ExitSignalSeverity.INFO
    assert not result2.triggered
