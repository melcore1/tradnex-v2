"""Underlying-based exit signals: halt + adverse gap."""

from datetime import UTC, datetime
from decimal import Decimal

from shared.clients.halt_feed import Halt
from shared.schemas.core import Position
from shared.schemas.market import Quote
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import ExitSignalSeverity
from shared.strategy.exit_signals.underlying import (
    signal_adverse_gap,
    signal_underlying_halted,
)


def _pos() -> Position:
    return Position(
        id=1, ticker="NVDA", contract_symbol="X", side="long", quantity=1,
        entry_price=Decimal("2.50"), entry_ts=0.0, status="open",
    )


def _quote(spot: Decimal, prev_close: Decimal) -> Quote:
    return Quote(
        ticker="NVDA",
        spot=spot,
        bid=spot,
        ask=spot,
        bid_size=10,
        ask_size=10,
        day_open=spot,
        day_high=spot,
        day_low=spot,
        prev_close=prev_close,
        volume=1_000_000,
        avg_volume_30d=80_000_000,
        is_market_open=True,
        timestamp=datetime.now(UTC),
    )


def test_halted_urgent() -> None:
    halt = Halt(
        ticker="NVDA",
        halt_time=datetime.now(UTC),
        halt_reason="Volatility",
        halt_code="LUDP",
        is_active=True,
    )
    result = signal_underlying_halted(_pos(), True, halt, ExitSettings())
    assert result.severity == ExitSignalSeverity.URGENT
    assert result.triggered
    assert "Volatility" in result.description


def test_adverse_gap_urgent_at_minus_5_pct() -> None:
    # spot=95, prev=100 → gap_pct = -5
    result = signal_adverse_gap(_pos(), _quote(Decimal("95"), Decimal("100")), ExitSettings())
    assert result.severity == ExitSignalSeverity.URGENT
    assert result.triggered


def test_adverse_gap_warning_at_minus_4_pct() -> None:
    result = signal_adverse_gap(_pos(), _quote(Decimal("96"), Decimal("100")), ExitSettings())
    assert result.severity == ExitSignalSeverity.WARNING
    assert result.triggered


def test_favorable_gap_info_not_triggered() -> None:
    # Long call gap UP 4% — favorable
    result = signal_adverse_gap(_pos(), _quote(Decimal("104"), Decimal("100")), ExitSettings())
    assert result.severity == ExitSignalSeverity.INFO
    assert not result.triggered


def test_halt_resolved_info_not_triggered() -> None:
    result = signal_underlying_halted(_pos(), False, None, ExitSettings())
    assert result.severity == ExitSignalSeverity.INFO
    assert not result.triggered
