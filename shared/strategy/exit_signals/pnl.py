"""P&L-based exit signals: take profit, stop loss, trailing stop."""

from __future__ import annotations

from decimal import Decimal

from shared.schemas.core import Position
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import (
    ExitSignal,
    ExitSignalCategory,
    ExitSignalSeverity,
)


def _pnl_pct(entry: Decimal, current: Decimal) -> Decimal:
    if entry <= 0:
        return Decimal("0")
    return (current - entry) / entry * Decimal("100")


def signal_take_profit(
    position: Position,
    current_contract_price: Decimal,
    settings: ExitSettings,
) -> ExitSignal:
    pnl = _pnl_pct(position.entry_price, current_contract_price)
    severity = ExitSignalSeverity.INFO
    triggered = False
    description = f"P&L {pnl:.2f}%"
    if pnl >= settings.auto_close_profit_pct:
        severity = ExitSignalSeverity.AUTO_CLOSE
        triggered = True
        description = (
            f"P&L {pnl:.2f}% >= auto-close threshold "
            f"{settings.auto_close_profit_pct}% — close immediately"
        )
    elif pnl >= settings.tp_zone_pct:
        severity = ExitSignalSeverity.URGENT
        triggered = True
        description = f"P&L {pnl:.2f}% in take-profit zone (>= {settings.tp_zone_pct}%)"
    elif pnl >= settings.tp_warning_pct:
        severity = ExitSignalSeverity.WARNING
        triggered = True
        description = (
            f"P&L {pnl:.2f}% approaching take-profit (>= {settings.tp_warning_pct}%)"
        )
    elif pnl > 0:
        description = f"P&L {pnl:.2f}% (positive but below alert)"
    return ExitSignal(
        name="take_profit",
        category=ExitSignalCategory.PNL,
        severity=severity,
        triggered=triggered,
        description=description,
        details={
            "pnl_pct": str(pnl),
            "entry": str(position.entry_price),
            "current": str(current_contract_price),
        },
        threshold_used={
            "auto_close_profit_pct": str(settings.auto_close_profit_pct),
            "tp_zone_pct": str(settings.tp_zone_pct),
            "tp_warning_pct": str(settings.tp_warning_pct),
        },
    )


def signal_stop_loss(
    position: Position,
    current_contract_price: Decimal,
    settings: ExitSettings,
) -> ExitSignal:
    pnl = _pnl_pct(position.entry_price, current_contract_price)
    severity = ExitSignalSeverity.INFO
    triggered = False
    description = f"P&L {pnl:.2f}%"
    if pnl <= settings.auto_close_loss_pct:
        severity = ExitSignalSeverity.AUTO_CLOSE
        triggered = True
        description = (
            f"P&L {pnl:.2f}% <= auto-close loss threshold "
            f"{settings.auto_close_loss_pct}% — close immediately"
        )
    elif pnl <= settings.sl_zone_pct:
        severity = ExitSignalSeverity.URGENT
        triggered = True
        description = f"P&L {pnl:.2f}% in stop-loss zone (<= {settings.sl_zone_pct}%)"
    elif pnl <= settings.sl_warning_pct:
        severity = ExitSignalSeverity.WARNING
        triggered = True
        description = (
            f"P&L {pnl:.2f}% approaching stop-loss (<= {settings.sl_warning_pct}%)"
        )
    elif pnl < 0:
        description = f"P&L {pnl:.2f}% (negative but above alert)"
    return ExitSignal(
        name="stop_loss",
        category=ExitSignalCategory.PNL,
        severity=severity,
        triggered=triggered,
        description=description,
        details={
            "pnl_pct": str(pnl),
            "entry": str(position.entry_price),
            "current": str(current_contract_price),
        },
        threshold_used={
            "auto_close_loss_pct": str(settings.auto_close_loss_pct),
            "sl_zone_pct": str(settings.sl_zone_pct),
            "sl_warning_pct": str(settings.sl_warning_pct),
        },
    )


def signal_trailing_stop(
    position: Position,
    current_contract_price: Decimal,
    high_water_mark_pct: Decimal | None,
    settings: ExitSettings,
) -> ExitSignal:
    """Trailing stop:
    - activated once HWM (max P&L) ever reaches `trail_activation_pct`
    - triggers when current P&L drops `trail_giveback_pct` below HWM after activation
    """
    pnl = _pnl_pct(position.entry_price, current_contract_price)
    activated = (
        high_water_mark_pct is not None
        and high_water_mark_pct >= settings.trail_activation_pct
    )
    if not activated:
        return ExitSignal(
            name="trailing_stop",
            category=ExitSignalCategory.PNL,
            severity=ExitSignalSeverity.INFO,
            triggered=False,
            description=(
                f"Trailing stop not activated (HWM "
                f"{high_water_mark_pct if high_water_mark_pct is not None else 'n/a'}% "
                f"< activation {settings.trail_activation_pct}%)"
            ),
            details={
                "pnl_pct": str(pnl),
                "high_water_mark_pct": str(high_water_mark_pct)
                if high_water_mark_pct is not None
                else None,
            },
            threshold_used={
                "trail_activation_pct": str(settings.trail_activation_pct),
                "trail_giveback_pct": str(settings.trail_giveback_pct),
            },
        )
    assert high_water_mark_pct is not None
    giveback = high_water_mark_pct - pnl
    triggered = giveback >= settings.trail_giveback_pct
    severity = ExitSignalSeverity.URGENT if triggered else ExitSignalSeverity.INFO
    description = (
        f"Trailing stop {'TRIGGERED' if triggered else 'tracking'}: "
        f"HWM {high_water_mark_pct}% / current {pnl:.2f}% / giveback {giveback}%"
    )
    return ExitSignal(
        name="trailing_stop",
        category=ExitSignalCategory.PNL,
        severity=severity,
        triggered=triggered,
        description=description,
        details={
            "pnl_pct": str(pnl),
            "high_water_mark_pct": str(high_water_mark_pct),
            "giveback_pct": str(giveback),
        },
        threshold_used={
            "trail_activation_pct": str(settings.trail_activation_pct),
            "trail_giveback_pct": str(settings.trail_giveback_pct),
        },
    )
