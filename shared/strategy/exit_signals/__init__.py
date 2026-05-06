"""Exit signal subpackage: pure functions that observe position state."""

from shared.strategy.exit_signals.base import (
    ExitSignal,
    ExitSignalCategory,
    ExitSignalSeverity,
    ExitSignalTrace,
)
from shared.strategy.exit_signals.greeks import (
    signal_charm_acceleration,
    signal_delta_too_high,
    signal_delta_too_low,
    signal_theta_acceleration,
    signal_vega_exposure,
)
from shared.strategy.exit_signals.pnl import (
    signal_stop_loss,
    signal_take_profit,
    signal_trailing_stop,
)
from shared.strategy.exit_signals.setup import signal_setup_invalidated
from shared.strategy.exit_signals.time import (
    signal_dte_critical,
    signal_friday_position_short_dte,
)
from shared.strategy.exit_signals.underlying import (
    signal_adverse_gap,
    signal_underlying_halted,
)
from shared.strategy.exit_signals.volatility import (
    signal_iv_crush,
    signal_iv_spike,
)

__all__ = [
    "ExitSignal",
    "ExitSignalCategory",
    "ExitSignalSeverity",
    "ExitSignalTrace",
    "signal_adverse_gap",
    "signal_charm_acceleration",
    "signal_delta_too_high",
    "signal_delta_too_low",
    "signal_dte_critical",
    "signal_friday_position_short_dte",
    "signal_iv_crush",
    "signal_iv_spike",
    "signal_setup_invalidated",
    "signal_stop_loss",
    "signal_take_profit",
    "signal_theta_acceleration",
    "signal_trailing_stop",
    "signal_underlying_halted",
    "signal_vega_exposure",
]
