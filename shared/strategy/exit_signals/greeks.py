"""Greek-based exit signals: delta zones, theta acceleration, vega, charm."""

from __future__ import annotations

from decimal import Decimal

from shared.schemas.core import Position
from shared.schemas.market import OptionContract
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import (
    ExitSignal,
    ExitSignalCategory,
    ExitSignalSeverity,
)


def signal_delta_too_high(
    position: Position,
    contract: OptionContract,
    settings: ExitSettings,
) -> ExitSignal:
    """Long calls only: delta crossing into deep-ITM territory.
    Short delta is signed differently; we use absolute value to be direction-agnostic."""
    delta = abs(contract.delta)
    severity = ExitSignalSeverity.INFO
    triggered = False
    description = f"|Delta| {delta}"
    if delta >= settings.delta_take_profit:
        severity = ExitSignalSeverity.URGENT
        triggered = True
        description = f"|Delta| {delta} >= take-profit zone {settings.delta_take_profit}"
    elif delta >= settings.delta_warning_high:
        severity = ExitSignalSeverity.WARNING
        triggered = True
        description = f"|Delta| {delta} approaching take-profit zone"
    return ExitSignal(
        name="delta_too_high",
        category=ExitSignalCategory.GREEK,
        severity=severity,
        triggered=triggered,
        description=description,
        details={"delta": str(delta), "abs_used": True},
        threshold_used={
            "delta_take_profit": str(settings.delta_take_profit),
            "delta_warning_high": str(settings.delta_warning_high),
        },
    )


def signal_delta_too_low(
    position: Position,
    contract: OptionContract,
    settings: ExitSettings,
) -> ExitSignal:
    delta = abs(contract.delta)
    severity = ExitSignalSeverity.INFO
    triggered = False
    description = f"|Delta| {delta}"
    if delta <= settings.delta_stop_loss:
        severity = ExitSignalSeverity.URGENT
        triggered = True
        description = (
            f"|Delta| {delta} <= stop-loss zone {settings.delta_stop_loss} (deep OTM, decay risk)"
        )
    elif delta <= settings.delta_warning_low:
        severity = ExitSignalSeverity.WARNING
        triggered = True
        description = f"|Delta| {delta} approaching stop-loss zone"
    return ExitSignal(
        name="delta_too_low",
        category=ExitSignalCategory.GREEK,
        severity=severity,
        triggered=triggered,
        description=description,
        details={"delta": str(delta), "abs_used": True},
        threshold_used={
            "delta_stop_loss": str(settings.delta_stop_loss),
            "delta_warning_low": str(settings.delta_warning_low),
        },
    )


def signal_theta_acceleration(
    position: Position,
    contract: OptionContract,
    settings: ExitSettings,
) -> ExitSignal:
    """Theta as % of position notional. Theta is per-day, signed (negative for longs).

    notional = mid * 100 * quantity.
    theta_dollars_per_day = abs(theta) * 100 * quantity.
    theta_pct = theta_dollars / notional * 100.
    """
    if position.quantity <= 0:
        return ExitSignal(
            name="theta_acceleration",
            category=ExitSignalCategory.GREEK,
            severity=ExitSignalSeverity.INFO,
            triggered=False,
            description="No position quantity — theta n/a",
            details={"quantity": position.quantity},
            threshold_used={},
        )
    notional = contract.mid * Decimal("100") * Decimal(position.quantity)
    if notional <= 0:
        return ExitSignal(
            name="theta_acceleration",
            category=ExitSignalCategory.GREEK,
            severity=ExitSignalSeverity.INFO,
            triggered=False,
            description="Notional <= 0 — theta n/a",
            details={"notional": str(notional)},
            threshold_used={},
        )
    theta_dollars = abs(contract.theta) * Decimal("100") * Decimal(position.quantity)
    theta_pct = theta_dollars / notional * Decimal("100")
    severity = ExitSignalSeverity.INFO
    triggered = False
    description = f"Theta {theta_pct:.2f}% of notional / day"
    if theta_pct >= settings.theta_critical_pct:
        severity = ExitSignalSeverity.URGENT
        triggered = True
        description = (
            f"Theta accelerating: {theta_pct:.2f}% / day >= "
            f"critical {settings.theta_critical_pct}%"
        )
    elif theta_pct >= settings.theta_warning_pct:
        severity = ExitSignalSeverity.WARNING
        triggered = True
        description = (
            f"Theta {theta_pct:.2f}% / day >= warning {settings.theta_warning_pct}%"
        )
    return ExitSignal(
        name="theta_acceleration",
        category=ExitSignalCategory.GREEK,
        severity=severity,
        triggered=triggered,
        description=description,
        details={
            "theta_pct": str(theta_pct),
            "theta_per_contract_per_day": str(contract.theta),
            "notional": str(notional),
        },
        threshold_used={
            "theta_critical_pct": str(settings.theta_critical_pct),
            "theta_warning_pct": str(settings.theta_warning_pct),
        },
    )


def signal_vega_exposure(
    position: Position,
    contract: OptionContract,
    settings: ExitSettings,
) -> ExitSignal:
    """Vega exposure as % of position notional. INFO-level by default;
    WARNING if exposure exceeds settings.vega_warning_pct_of_notional."""
    if position.quantity <= 0:
        return ExitSignal(
            name="vega_exposure",
            category=ExitSignalCategory.GREEK,
            severity=ExitSignalSeverity.INFO,
            triggered=False,
            description="No position quantity — vega n/a",
            details={"quantity": position.quantity},
            threshold_used={},
        )
    notional = contract.mid * Decimal("100") * Decimal(position.quantity)
    if notional <= 0:
        return ExitSignal(
            name="vega_exposure",
            category=ExitSignalCategory.GREEK,
            severity=ExitSignalSeverity.INFO,
            triggered=False,
            description="Notional <= 0 — vega n/a",
            details={"notional": str(notional)},
            threshold_used={},
        )
    vega_dollars_per_pct = (
        abs(contract.vega) * Decimal("100") * Decimal(position.quantity)
    )
    vega_pct_of_notional = vega_dollars_per_pct / notional * Decimal("100")
    severity = ExitSignalSeverity.INFO
    triggered = False
    description = f"Vega {vega_pct_of_notional:.2f}% of notional per 1% IV move"
    if vega_pct_of_notional >= settings.vega_warning_pct_of_notional:
        severity = ExitSignalSeverity.WARNING
        triggered = True
        description = (
            f"Vega exposure {vega_pct_of_notional:.2f}% / 1%IV "
            f">= warning {settings.vega_warning_pct_of_notional}%"
        )
    return ExitSignal(
        name="vega_exposure",
        category=ExitSignalCategory.GREEK,
        severity=severity,
        triggered=triggered,
        description=description,
        details={
            "vega_pct_of_notional": str(vega_pct_of_notional),
            "vega_per_contract": str(contract.vega),
        },
        threshold_used={
            "vega_warning_pct_of_notional": str(settings.vega_warning_pct_of_notional),
        },
    )


def signal_charm_acceleration(
    position: Position,
    contract: OptionContract,
    settings: ExitSettings,
) -> ExitSignal:
    """Informational only: short DTE + non-trivial gamma flags charm
    sensitivity. Always INFO; reports the magnitude for Claude consumption."""
    description = (
        f"DTE {contract.dte}, gamma {contract.gamma}; charm dynamic noted"
    )
    return ExitSignal(
        name="charm_acceleration",
        category=ExitSignalCategory.GREEK,
        severity=ExitSignalSeverity.INFO,
        triggered=False,
        description=description,
        details={"dte": contract.dte, "gamma": str(contract.gamma)},
        threshold_used={},
    )
