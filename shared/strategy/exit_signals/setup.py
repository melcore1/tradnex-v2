"""Setup-invalidation signal: re-evaluate the entry strategy's hard rules."""

from __future__ import annotations

from shared.analytics.full_analysis import FullAnalysis
from shared.schemas.core import Position
from shared.schemas.market import Bar
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import (
    ExitSignal,
    ExitSignalCategory,
    ExitSignalSeverity,
)


def signal_setup_invalidated(
    position: Position,
    full_analysis: FullAnalysis,
    bars_5m: list[Bar],
    settings: ExitSettings,
) -> ExitSignal:
    """Re-run the 6-rule strategy's hard rules against current state. The
    severity scales with how many rules now fail."""
    # Lazy import: avoids circular dependency with shared.strategy.base
    from shared.strategy.long_options_momentum import LongOptionsMomentum

    strategy = LongOptionsMomentum()
    h1 = strategy._evaluate_h1_above_200_sma(full_analysis)
    h2 = strategy._evaluate_h2_ema_alignment(bars_5m)
    h3 = strategy._evaluate_h3_macd_divergence(bars_5m)
    failed = [r.name for r in (h1, h2, h3) if not r.passed]
    failed_count = len(failed)

    severity = ExitSignalSeverity.INFO
    triggered = False
    description = "All hard rules still hold"
    if failed_count >= 2:
        severity = ExitSignalSeverity.URGENT
        triggered = True
        description = f"{failed_count}/3 hard rules now fail: {failed}"
    elif failed_count == 1:
        severity = ExitSignalSeverity.WARNING
        triggered = True
        description = f"1/3 hard rule now fails: {failed[0]}"

    return ExitSignal(
        name="setup_invalidated",
        category=ExitSignalCategory.SETUP_INVALIDATED,
        severity=severity,
        triggered=triggered,
        description=description,
        details={
            "failed_rules": failed,
            "failed_count": failed_count,
            "h1_passed": h1.passed,
            "h2_passed": h2.passed,
            "h3_passed": h3.passed,
        },
        threshold_used={},
    )
