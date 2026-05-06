"""P&L-based exit signals: take-profit, stop-loss, trailing stop."""

from decimal import Decimal

from shared.schemas.core import Position
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import ExitSignalSeverity
from shared.strategy.exit_signals.pnl import (
    signal_stop_loss,
    signal_take_profit,
    signal_trailing_stop,
)


def _pos(entry: Decimal = Decimal("2.50"), qty: int = 1) -> Position:
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


def test_take_profit_auto_close_at_52_pct() -> None:
    settings = ExitSettings()
    # entry=2, current=3.04 → +52%
    result = signal_take_profit(_pos(entry=Decimal("2.00")), Decimal("3.04"), settings)
    assert result.severity == ExitSignalSeverity.AUTO_CLOSE
    assert result.triggered


def test_take_profit_urgent_at_30_pct() -> None:
    settings = ExitSettings()
    # entry=2, current=2.6 → +30%
    result = signal_take_profit(_pos(entry=Decimal("2.00")), Decimal("2.60"), settings)
    assert result.severity == ExitSignalSeverity.URGENT
    assert result.triggered


def test_take_profit_warning_at_18_pct() -> None:
    settings = ExitSettings()
    result = signal_take_profit(_pos(entry=Decimal("2.00")), Decimal("2.36"), settings)
    assert result.severity == ExitSignalSeverity.WARNING
    assert result.triggered


def test_take_profit_info_when_positive_below_warning() -> None:
    settings = ExitSettings()
    # +5%
    result = signal_take_profit(_pos(entry=Decimal("2.00")), Decimal("2.10"), settings)
    assert result.severity == ExitSignalSeverity.INFO


def test_stop_loss_auto_close_at_minus_45_pct() -> None:
    settings = ExitSettings()
    # entry=2, current=1.10 → -45%
    result = signal_stop_loss(_pos(entry=Decimal("2.00")), Decimal("1.10"), settings)
    assert result.severity == ExitSignalSeverity.AUTO_CLOSE
    assert result.triggered


def test_stop_loss_urgent_at_minus_28_pct() -> None:
    settings = ExitSettings()
    result = signal_stop_loss(_pos(entry=Decimal("2.00")), Decimal("1.44"), settings)
    assert result.severity == ExitSignalSeverity.URGENT
    assert result.triggered


def test_trailing_stop_not_activated_when_hwm_below_threshold() -> None:
    settings = ExitSettings()
    # HWM 20% < activation 25%
    result = signal_trailing_stop(
        _pos(entry=Decimal("2.00")), Decimal("2.20"), Decimal("20"), settings
    )
    assert result.severity == ExitSignalSeverity.INFO
    assert not result.triggered


def test_trailing_stop_activated_then_triggered() -> None:
    settings = ExitSettings()
    # HWM=40% (activated), current pnl=20% → giveback 20% > 15%
    result = signal_trailing_stop(
        _pos(entry=Decimal("2.00")), Decimal("2.40"), Decimal("40"), settings
    )
    assert result.severity == ExitSignalSeverity.URGENT
    assert result.triggered
    # Activated but not yet triggered: HWM=40, current=35% → giveback 5% < 15%
    result2 = signal_trailing_stop(
        _pos(entry=Decimal("2.00")), Decimal("2.70"), Decimal("40"), settings
    )
    assert result2.severity == ExitSignalSeverity.INFO
    assert not result2.triggered
