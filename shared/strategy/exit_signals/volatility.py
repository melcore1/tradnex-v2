"""Volatility-based exit signals: IV crush, IV spike."""

from __future__ import annotations

from decimal import Decimal

from shared.schemas.core import Position
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import (
    ExitSignal,
    ExitSignalCategory,
    ExitSignalSeverity,
)


def _iv_change_pct(entry_iv: Decimal | None, current_iv: Decimal) -> Decimal | None:
    if entry_iv is None or entry_iv <= 0:
        return None
    return (current_iv - entry_iv) / entry_iv * Decimal("100")


def signal_iv_crush(
    position: Position,
    current_iv: Decimal,
    entry_iv: Decimal | None,
    settings: ExitSettings,
) -> ExitSignal:
    change = _iv_change_pct(entry_iv, current_iv)
    if change is None:
        return ExitSignal(
            name="iv_crush",
            category=ExitSignalCategory.VOLATILITY,
            severity=ExitSignalSeverity.INFO,
            triggered=False,
            description="No entry_iv recorded — IV crush n/a",
            details={"current_iv": str(current_iv)},
            threshold_used={},
        )
    drop_pct = -change  # positive value when IV dropped
    severity = ExitSignalSeverity.INFO
    triggered = False
    description = f"IV change since entry: {change:.2f}%"
    if drop_pct >= settings.iv_crush_critical_pct:
        severity = ExitSignalSeverity.URGENT
        triggered = True
        description = (
            f"IV crushed {drop_pct:.2f}% from entry "
            f">= critical {settings.iv_crush_critical_pct}%"
        )
    elif drop_pct >= settings.iv_crush_warning_pct:
        severity = ExitSignalSeverity.WARNING
        triggered = True
        description = (
            f"IV down {drop_pct:.2f}% from entry "
            f">= warning {settings.iv_crush_warning_pct}%"
        )
    return ExitSignal(
        name="iv_crush",
        category=ExitSignalCategory.VOLATILITY,
        severity=severity,
        triggered=triggered,
        description=description,
        details={
            "iv_change_pct": str(change),
            "iv_drop_pct": str(drop_pct),
            "entry_iv": str(entry_iv),
            "current_iv": str(current_iv),
        },
        threshold_used={
            "iv_crush_critical_pct": str(settings.iv_crush_critical_pct),
            "iv_crush_warning_pct": str(settings.iv_crush_warning_pct),
        },
    )


def signal_iv_spike(
    position: Position,
    current_iv: Decimal,
    entry_iv: Decimal | None,
    settings: ExitSettings,
) -> ExitSignal:
    change = _iv_change_pct(entry_iv, current_iv)
    if change is None:
        return ExitSignal(
            name="iv_spike",
            category=ExitSignalCategory.VOLATILITY,
            severity=ExitSignalSeverity.INFO,
            triggered=False,
            description="No entry_iv recorded — IV spike n/a",
            details={"current_iv": str(current_iv)},
            threshold_used={},
        )
    severity = ExitSignalSeverity.INFO
    triggered = False
    description = f"IV change since entry: {change:.2f}%"
    if change >= settings.iv_spike_warning_pct:
        severity = ExitSignalSeverity.WARNING
        triggered = True
        description = (
            f"IV spiked {change:.2f}% from entry "
            f">= warning {settings.iv_spike_warning_pct}% — consider exit before reversal"
        )
    elif change >= settings.iv_spike_info_pct:
        triggered = False
        description = f"IV up {change:.2f}% from entry — noted"
    return ExitSignal(
        name="iv_spike",
        category=ExitSignalCategory.VOLATILITY,
        severity=severity,
        triggered=triggered,
        description=description,
        details={
            "iv_change_pct": str(change),
            "entry_iv": str(entry_iv),
            "current_iv": str(current_iv),
        },
        threshold_used={
            "iv_spike_warning_pct": str(settings.iv_spike_warning_pct),
            "iv_spike_info_pct": str(settings.iv_spike_info_pct),
        },
    )
