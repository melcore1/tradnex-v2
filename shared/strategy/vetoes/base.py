"""Veto types: VetoResult, VetoTrace, VetoContext, VetoSettings.

Vetoes are pure async functions: (candidate, ctx) -> VetoResult. They
observe state and report whether they want to block; the orchestrator
decides what to do with the trace.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.clients.halt_feed import HaltFeed
from shared.services.calendar_service import CalendarService


class VetoResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    failed: bool
    failure_reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class VetoTrace(BaseModel):
    model_config = ConfigDict(frozen=False)

    candidate_id: int
    veto_set: Literal["entry", "exit"]
    timestamp: datetime
    results: list[VetoResult]
    any_failed: bool
    failed_veto_names: list[str]


class VetoSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    weekly_trade_cap: int = 10
    weekly_loss_circuit_breaker_pct: Decimal = Decimal("-3")
    account_notional_for_pct: Decimal = Decimal("100000")
    concurrent_positions_cap: int = 5
    earnings_blackout_days_before: int = 7
    earnings_blackout_days_after: int = 1
    macro_event_blackout_hours: int = 24
    macro_event_min_impact: Literal["low", "medium", "high"] = "medium"
    vix_spike_threshold: Decimal = Decimal("30")
    vix_veto_enabled: bool = False
    duplicate_window_minutes: int = 30
    exit_window_cutoff_et: str = "15:55"
    exit_duplicate_window_minutes: int = 5


class OrchestratorCandidate(BaseModel):
    """Lightweight candidate view for veto evaluation. Reconstructed from
    the candidates row by `load_candidate`. Avoids requiring full
    FullAnalysis / RegimeState / OptionsAnalysis hydration just to run
    deterministic checks."""

    model_config = ConfigDict(frozen=True)

    id: int
    candidate_kind: Literal["entry", "exit"]
    ticker: str
    direction: Literal["long_call", "long_put"]
    status: str
    created_ts: float
    position_id: int | None = None
    is_auto_close: bool = False


class VetoContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    conn: sqlite3.Connection
    calendar_service: CalendarService
    halt_feed: HaltFeed
    settings: VetoSettings
    market_window_start_et: str = "09:45"
    market_window_end_et: str = "15:00"
    current_time_utc: datetime
