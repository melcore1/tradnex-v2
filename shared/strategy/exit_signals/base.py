"""Exit-signal types: ExitSignal, ExitSignalTrace, severity/category enums."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


class ExitSignalCategory(StrEnum):
    PNL = "pnl"
    GREEK = "greek"
    VOLATILITY = "volatility"
    TIME = "time"
    UNDERLYING = "underlying"
    SETUP_INVALIDATED = "setup_invalidated"


class ExitSignalSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    URGENT = "urgent"
    AUTO_CLOSE = "auto_close"


class ExitSignal(BaseModel):
    """One observation about a position. Pure data; never decides."""

    model_config = ConfigDict(frozen=True)

    name: str
    category: ExitSignalCategory
    severity: ExitSignalSeverity
    triggered: bool
    description: str
    details: dict[str, Any] = Field(default_factory=dict)
    threshold_used: dict[str, Any] = Field(default_factory=dict)


class ExitSignalTrace(BaseModel):
    """Complete signal evaluation for one position at one cycle."""

    model_config = ConfigDict(frozen=False)

    position_id: int
    timestamp: datetime

    ticker: str
    contract_symbol: str
    entry_price: Decimal
    current_price: Decimal
    pnl_pct: Decimal
    pnl_dollars: Decimal
    quantity: int
    dte_remaining: int

    signals: list[ExitSignal]

    auto_close_triggered: bool
    auto_close_reason: str | None
    urgent_count: int
    warning_count: int
    info_count: int

    needs_claude: bool

    @computed_field  # type: ignore[prop-decorator]
    @property
    def triggered_signal_names(self) -> list[str]:
        return [s.name for s in self.signals if s.triggered]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> str:
        bits = [
            f"{self.contract_symbol}: pnl {self.pnl_pct}%",
        ]
        if self.auto_close_triggered:
            bits.append(f"AUTO_CLOSE ({self.auto_close_reason})")
        else:
            bits.append(
                f"{self.urgent_count} urgent / "
                f"{self.warning_count} warning / "
                f"{self.info_count} info"
            )
            if self.needs_claude:
                bits.append("→ Claude")
            else:
                bits.append("→ hold")
        return ", ".join(bits)
