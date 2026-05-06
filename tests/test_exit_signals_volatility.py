"""IV-based exit signals."""

from decimal import Decimal

from shared.schemas.core import Position
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import ExitSignalSeverity
from shared.strategy.exit_signals.volatility import signal_iv_crush, signal_iv_spike


def _pos() -> Position:
    return Position(
        id=1, ticker="NVDA", contract_symbol="X", side="long", quantity=1,
        entry_price=Decimal("2.50"), entry_ts=0.0, status="open",
    )


def test_iv_crush_urgent_at_35_pct_drop() -> None:
    # entry IV 0.40 → current 0.26 = -35%
    result = signal_iv_crush(_pos(), Decimal("0.26"), Decimal("0.40"), ExitSettings())
    assert result.severity == ExitSignalSeverity.URGENT
    assert result.triggered


def test_iv_crush_warning_at_20_pct_drop() -> None:
    # entry 0.40 → current 0.32 = -20%
    result = signal_iv_crush(_pos(), Decimal("0.32"), Decimal("0.40"), ExitSettings())
    assert result.severity == ExitSignalSeverity.WARNING
    assert result.triggered


def test_iv_spike_warning_at_35_pct_jump() -> None:
    result = signal_iv_spike(_pos(), Decimal("0.54"), Decimal("0.40"), ExitSettings())
    assert result.severity == ExitSignalSeverity.WARNING
    assert result.triggered


def test_iv_change_info_when_stable() -> None:
    # No entry IV → INFO not triggered
    crush = signal_iv_crush(_pos(), Decimal("0.32"), None, ExitSettings())
    assert crush.severity == ExitSignalSeverity.INFO
    assert not crush.triggered
    spike = signal_iv_spike(_pos(), Decimal("0.32"), None, ExitSettings())
    assert spike.severity == ExitSignalSeverity.INFO
    assert not spike.triggered
