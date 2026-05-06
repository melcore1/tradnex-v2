"""Strategy types: rule traces, candidates, and the Strategy Protocol.

Defines the entry/exit candidate split used by the scanner (entry only in
Phase 3) and the orchestrator (exit, Phase 3.5). The Strategy Protocol is
duck-typed — any class with `name`, `settings`, and `evaluate_entry()` works.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from shared.analytics.full_analysis import FullAnalysis
from shared.analytics.options.full_options_analysis import FullOptionsAnalysis
from shared.analytics.regime import RegimeState
from shared.schemas.market import Bar, OptionContract
from shared.strategy.exit_signals.base import ExitSignalTrace


class RuleType(StrEnum):
    HARD = "hard"
    SOFT = "soft"


ConfidenceLabel = Literal["STRONG", "MODERATE", "WEAK", "VETO"]
EntryDirection = Literal["long_call", "long_put"]
PositionLifecycleState = Literal[
    "open",
    "closing_pending_approval",
    "closing",
    "closed",
]
ExitSignalType = Literal[
    "time_based",
    "pnl_based",
    "greek_based",
    "volatility_based",
    "underlying_based",
    "soft_setup_invalidated",
    "soft_news_changed",
]


class RuleResult(BaseModel):
    """Result of evaluating one rule."""

    model_config = ConfigDict(frozen=True)

    name: str
    rule_type: RuleType
    passed: bool
    score: int = 0
    max_score: int = 1
    details: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None


class RuleTrace(BaseModel):
    """Full evaluation trace for one ticker — fired or not."""

    model_config = ConfigDict(frozen=False)

    timestamp: datetime
    ticker: str
    timeframe_5m: str = "5m"
    timeframe_daily: str = "1d"

    hard_rules: list[RuleResult]
    soft_rules: list[RuleResult]

    all_hard_passed: bool
    soft_score: int
    soft_max_score: int

    confidence_label: ConfidenceLabel
    confidence_score: Decimal

    fired: bool
    fire_decision_reason: str


class EntryCandidate(BaseModel):
    """Candidate for opening a position."""

    model_config = ConfigDict(frozen=False)

    candidate_kind: Literal["entry"] = "entry"
    ticker: str
    direction: EntryDirection
    strategy_name: str

    rule_trace: RuleTrace
    full_analysis: FullAnalysis
    options_analysis: FullOptionsAnalysis | None
    regime: RegimeState

    overrides_applied: dict[str, Any] = Field(default_factory=dict)

    confidence: Literal["STRONG", "MODERATE", "WEAK"]
    sizing_multiplier: Decimal
    max_premium: Decimal

    shortlist: list[OptionContract] | None = None

    # Phase 5: chosen contract from shortlist. Populated by either the
    # LLM evaluator or, when llm_enabled=False, by the scanner via
    # select_default_contract. Persisted to candidates.selected_contract_json.
    selected_contract: OptionContract | None = None

    timestamp: datetime


class ExitCandidate(BaseModel):
    """Candidate for closing an open position.

    Routing flags (`is_auto_close`, `needs_claude`) are mutually exclusive
    once the exit_evaluator returns. The orchestrator (Phase 4) reads them
    to decide whether to bypass Claude (`is_auto_close=True`) or send the
    candidate to LLM evaluation (`needs_claude=True`). Either path ends at
    human approval before any close order leaves.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    candidate_kind: Literal["exit"] = "exit"
    position_id: int
    ticker: str
    exit_signal_type: ExitSignalType

    # Routing
    is_auto_close: bool = False
    needs_claude: bool = False
    auto_close_reason: str | None = None
    triggered_signals: list[str] = Field(default_factory=list)

    # Full trace
    signal_trace: ExitSignalTrace

    # Convenience snapshot
    pnl_pct: Decimal
    pnl_dollars: Decimal
    dte_remaining: int

    timestamp: datetime


Candidate = EntryCandidate | ExitCandidate


class Strategy(Protocol):
    """Strategy contract. v1 has one impl (LongOptionsMomentum)."""

    name: str

    async def evaluate_entry(
        self,
        ticker: str,
        bars_5m: list[Bar],
        bars_daily: list[Bar],
        full_analysis: FullAnalysis,
        options_analysis: FullOptionsAnalysis | None,
        regime: RegimeState,
        overrides: dict[str, Any],
    ) -> tuple[RuleTrace, EntryCandidate | None]: ...
