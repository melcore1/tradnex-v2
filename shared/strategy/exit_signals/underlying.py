"""Underlying-based exit signals: trading halt, adverse gap."""

from __future__ import annotations

from decimal import Decimal

from shared.clients.halt_feed import Halt
from shared.schemas.core import Position
from shared.schemas.market import Quote
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import (
    ExitSignal,
    ExitSignalCategory,
    ExitSignalSeverity,
)


def signal_underlying_halted(
    position: Position,
    is_halted: bool,
    halt_info: Halt | None,
    settings: ExitSettings,
) -> ExitSignal:
    if is_halted:
        return ExitSignal(
            name="underlying_halted",
            category=ExitSignalCategory.UNDERLYING,
            severity=ExitSignalSeverity.URGENT,
            triggered=True,
            description=(
                f"{position.ticker} HALTED"
                + (f": {halt_info.halt_reason}" if halt_info else "")
            ),
            details={
                "halt_reason": halt_info.halt_reason if halt_info else None,
                "halt_code": halt_info.halt_code if halt_info else None,
                "halt_time": halt_info.halt_time.isoformat() if halt_info else None,
            },
            threshold_used={},
        )
    return ExitSignal(
        name="underlying_halted",
        category=ExitSignalCategory.UNDERLYING,
        severity=ExitSignalSeverity.INFO,
        triggered=False,
        description=f"{position.ticker} trading normally",
        details={},
        threshold_used={},
    )


def signal_adverse_gap(
    position: Position,
    quote: Quote,
    settings: ExitSettings,
) -> ExitSignal:
    """For long calls, an adverse gap is *down*. (Long puts inverted, but
    Phase 3 only emits long_call entries.)"""
    if quote.prev_close <= 0:
        return ExitSignal(
            name="adverse_gap",
            category=ExitSignalCategory.UNDERLYING,
            severity=ExitSignalSeverity.INFO,
            triggered=False,
            description="No prev_close — gap n/a",
            details={"prev_close": str(quote.prev_close)},
            threshold_used={},
        )
    gap_pct = (quote.spot - quote.prev_close) / quote.prev_close * Decimal("100")
    # Long call: adverse = down (negative gap_pct).
    # Use absolute negative magnitude.
    adverse_pct = -gap_pct  # positive when gap down

    severity = ExitSignalSeverity.INFO
    triggered = False
    description = f"Underlying gap {gap_pct:.2f}%"
    if adverse_pct >= settings.adverse_gap_critical_pct:
        severity = ExitSignalSeverity.URGENT
        triggered = True
        description = (
            f"Underlying gapped DOWN {adverse_pct:.2f}% "
            f">= critical {settings.adverse_gap_critical_pct}% (long call adverse)"
        )
    elif adverse_pct >= settings.adverse_gap_warning_pct:
        severity = ExitSignalSeverity.WARNING
        triggered = True
        description = (
            f"Underlying gapped DOWN {adverse_pct:.2f}% "
            f">= warning {settings.adverse_gap_warning_pct}% (long call adverse)"
        )
    elif gap_pct > 0:
        description = f"Favorable gap UP {gap_pct:.2f}% for long call"
    return ExitSignal(
        name="adverse_gap",
        category=ExitSignalCategory.UNDERLYING,
        severity=severity,
        triggered=triggered,
        description=description,
        details={
            "gap_pct": str(gap_pct),
            "adverse_pct": str(adverse_pct),
            "prev_close": str(quote.prev_close),
            "spot": str(quote.spot),
        },
        threshold_used={
            "adverse_gap_critical_pct": str(settings.adverse_gap_critical_pct),
            "adverse_gap_warning_pct": str(settings.adverse_gap_warning_pct),
        },
    )
