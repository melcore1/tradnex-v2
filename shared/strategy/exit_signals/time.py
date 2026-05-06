"""Time-based exit signals: DTE proximity, Friday-short-DTE."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from shared.schemas.core import Position
from shared.schemas.market import OptionContract
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import (
    ExitSignal,
    ExitSignalCategory,
    ExitSignalSeverity,
)

ET = ZoneInfo("America/New_York")
MARKET_CLOSE_ET = time(16, 0)


def signal_dte_critical(
    position: Position,
    contract: OptionContract,
    now_dt: datetime,
    settings: ExitSettings,
) -> ExitSignal:
    """DTE proximity. Severity ladder:
    - URGENT: dte == 0 (expiration day)
    - URGENT: dte == 1 AND after 13:00 ET
    - WARNING: dte <= 2
    - INFO: dte <= 5
    - INFO (not triggered): dte > 5
    """
    dte = contract.dte
    now_et = now_dt.astimezone(ET)
    severity = ExitSignalSeverity.INFO
    triggered = False
    description = f"DTE {dte}"
    if dte <= 0:
        severity = ExitSignalSeverity.URGENT
        triggered = True
        description = "0 DTE — expiration today; manage or close before close"
    elif dte == 1 and now_et.time() >= time(13, 0):
        severity = ExitSignalSeverity.URGENT
        triggered = True
        description = "DTE 1 + afternoon — gamma risk into close"
    elif dte <= 2:
        severity = ExitSignalSeverity.WARNING
        triggered = True
        description = f"DTE {dte} — short-dated"
    elif dte <= 5:
        triggered = False
        description = f"DTE {dte} — under a week"
    return ExitSignal(
        name="dte_critical",
        category=ExitSignalCategory.TIME,
        severity=severity,
        triggered=triggered,
        description=description,
        details={"dte": dte, "now_et": now_et.isoformat(timespec="minutes")},
        threshold_used={"market_close_et": MARKET_CLOSE_ET.isoformat()},
    )


def signal_friday_position_short_dte(
    position: Position,
    contract: OptionContract,
    now_dt: datetime,
    settings: ExitSettings,
) -> ExitSignal:
    """Friday afternoon + short DTE → weekend gamma + theta drag."""
    now_et = now_dt.astimezone(ET)
    is_friday = now_et.weekday() == 4
    is_afternoon = now_et.time() >= time(13, 0)
    dte = contract.dte
    if is_friday and is_afternoon and dte <= 7:
        return ExitSignal(
            name="friday_short_dte",
            category=ExitSignalCategory.TIME,
            severity=ExitSignalSeverity.WARNING,
            triggered=True,
            description=(
                f"Friday afternoon + DTE {dte}: weekend theta drag without "
                "underlying movement to compensate"
            ),
            details={
                "dte": dte,
                "weekday": now_et.weekday(),
                "now_et": now_et.isoformat(timespec="minutes"),
            },
            threshold_used={"max_dte": 7},
        )
    return ExitSignal(
        name="friday_short_dte",
        category=ExitSignalCategory.TIME,
        severity=ExitSignalSeverity.INFO,
        triggered=False,
        description=f"Not friday-short-dte scenario (weekday {now_et.weekday()}, dte {dte})",
        details={
            "dte": dte,
            "weekday": now_et.weekday(),
            "is_friday": is_friday,
            "is_afternoon": is_afternoon,
        },
        threshold_used={"max_dte": 7},
    )
