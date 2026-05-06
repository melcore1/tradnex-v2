"""API request / response schemas (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Pydantic v2 serializes Decimal as string by default in model_dump_json,
# which preserves precision. JSON responses always use UTC ISO-8601 for
# datetimes via model_config = ConfigDict(...) on BaseModel subclasses.


# ---- Auth ----


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class LoginResponse(BaseModel):
    user: str  # email
    expires_at: datetime


class MeResponse(BaseModel):
    id: int
    email: str
    last_login_ts: datetime | None = None


# ---- Candidates ----


class CandidateSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    candidate_kind: Literal["entry", "exit"]
    ticker: str
    direction: str
    status: str
    confidence: str | None = None
    created_ts: datetime
    summary_text: str


class CandidateDetail(BaseModel):
    candidate: dict[str, Any]
    rule_trace: dict[str, Any] | None = None
    veto_trace: dict[str, Any] | None = None
    selected_contract: dict[str, Any] | None = None
    llm_evaluation: dict[str, Any] | None = None
    lifecycle_events: list[dict[str, Any]] = Field(default_factory=list)
    copyable_text: str  # everything as a single block, ready to paste


class FullContextResponse(BaseModel):
    """Lightweight version of CandidateDetail for the 'Copy Full Context'
    flow. Returns just the markdown without the structured payload."""

    copyable_text: str


class ApproveRequest(BaseModel):
    notes: str | None = None
    quantity_override: int | None = Field(default=None, ge=1)


class RejectRequest(BaseModel):
    notes: str | None = None
    reason: str | None = None


class CandidateActionResponse(BaseModel):
    id: int
    new_status: str
    already_processed: bool


# ---- Positions ----


class PositionSummary(BaseModel):
    id: int
    ticker: str
    contract_symbol: str
    side: str
    quantity: int
    entry_price: Decimal
    entry_ts: datetime
    status: str
    pnl: Decimal | None = None
    pnl_pct: Decimal | None = None


class PositionDetail(BaseModel):
    position: dict[str, Any]
    lifecycle_events: list[dict[str, Any]] = Field(default_factory=list)
    latest_monitor_evaluation: dict[str, Any] | None = None
    pending_exit_candidate: dict[str, Any] | None = None


# ---- Watchlist / universe ----


class WatchlistResponse(BaseModel):
    date: str  # YYYY-MM-DD
    tickers: list[str]
    per_ticker_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    notes: str | None = None


class WatchlistSetRequest(BaseModel):
    tickers: list[str]
    per_ticker_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    notes: str | None = None
    date: str | None = None  # default = today


class UniverseResponse(BaseModel):
    tickers: list[str]


class UniverseAddRequest(BaseModel):
    tickers: list[str]


# ---- Settings / system / prompts ----


class SettingsResponse(BaseModel):
    settings_json: dict[str, Any]


class SettingsUpdateRequest(BaseModel):
    updates: dict[str, Any]


class SystemStatusResponse(BaseModel):
    paused: bool
    monitor_paused: bool
    llm_enabled: bool
    queue_depth: int
    queue_in_flight: int
    open_positions: int
    pending_human_approvals: int
    # Phase 7: UI-visible context.
    # `trading_mode` is hard-coded "paper" until Phase 8 introduces live
    # trading. The field is exposed now so Phase 8 only flips a value, not
    # a schema. `override_reasons` carries human-readable explanations of
    # why a toggle is forced (e.g. "Monitor forced active — 1 open
    # position").
    trading_mode: Literal["paper", "live"] = "paper"
    override_reasons: dict[str, str | None] = Field(default_factory=dict)


class ToggleRequest(BaseModel):
    name: Literal["paused", "monitor_paused", "llm_enabled"]
    enabled: bool


class PromptVersionResponse(BaseModel):
    id: int
    template_name: str
    version_number: int
    template_text: str
    response_schema: dict[str, Any]
    status: str
    created_ts: datetime
    created_by: str
    activated_ts: datetime | None = None
    deprecated_ts: datetime | None = None
    notes: str | None = None


class PromptCreateRequest(BaseModel):
    template_name: Literal["entry_evaluation", "exit_evaluation"]
    template_text: str = Field(min_length=10)
    response_schema: dict[str, Any]
    notes: str | None = None


class PromptActivateRequest(BaseModel):
    version_id: int


# ---- Dashboard ----


class DashboardSummary(BaseModel):
    today_watchlist: WatchlistResponse | None = None
    open_positions_count: int
    open_positions_total_pnl: Decimal | None = None
    pending_human_approvals: int
    pending_llm_evaluations: int
    recent_events: list[dict[str, Any]]
    system_status: SystemStatusResponse


class MorningView(BaseModel):
    yesterday_results: dict[str, Any]
    today_watchlist: WatchlistResponse | None = None
    universe: list[str]
    upcoming_calendar: list[dict[str, Any]]
    pre_market_gaps: list[dict[str, Any]] = Field(default_factory=list)


class ActiveTrade(BaseModel):
    position: PositionSummary
    latest_monitor_evaluation: dict[str, Any] | None = None
    pending_exit_candidate_id: int | None = None


class JournalEntry(BaseModel):
    date: str
    scanner_cycles_run: int
    candidates_fired: int
    decisions: dict[str, int]  # by status
    position_state_changes: list[dict[str, Any]]
    pnl_dollars: Decimal | None = None
