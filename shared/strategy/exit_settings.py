"""Exit-engine configurable thresholds.

Lives at strategy_configs.settings_json["exit_settings"] in production; for
v1 the monitor instantiates with defaults.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ExitSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    # P&L thresholds (percentages)
    auto_close_profit_pct: Decimal = Decimal("50")
    auto_close_loss_pct: Decimal = Decimal("-40")
    tp_zone_pct: Decimal = Decimal("25")
    tp_warning_pct: Decimal = Decimal("15")
    sl_zone_pct: Decimal = Decimal("-25")
    sl_warning_pct: Decimal = Decimal("-15")

    # Trailing stop
    trail_activation_pct: Decimal = Decimal("25")
    trail_giveback_pct: Decimal = Decimal("15")

    # Greek thresholds
    delta_take_profit: Decimal = Decimal("0.70")
    delta_stop_loss: Decimal = Decimal("0.10")
    delta_warning_high: Decimal = Decimal("0.60")
    delta_warning_low: Decimal = Decimal("0.15")
    theta_critical_pct: Decimal = Decimal("5")
    theta_warning_pct: Decimal = Decimal("3")
    vega_warning_pct_of_notional: Decimal = Decimal("10")

    # IV thresholds (percent change since entry)
    iv_crush_critical_pct: Decimal = Decimal("30")
    iv_crush_warning_pct: Decimal = Decimal("20")
    iv_spike_warning_pct: Decimal = Decimal("30")
    iv_spike_info_pct: Decimal = Decimal("15")

    # Underlying gap thresholds (percent vs prev close)
    adverse_gap_critical_pct: Decimal = Decimal("5")
    adverse_gap_warning_pct: Decimal = Decimal("3")

    # Scheduler / window
    monitor_cadence_minutes: int = 5
    monitor_window_start_et: str = "09:30"
    monitor_window_end_et: str = "15:55"

    # Mode flags
    llm_enabled: bool = True
    monitor_enabled: bool = True
