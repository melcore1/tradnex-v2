from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CandidateStatus = Literal[
    "pending",
    "rules_passed",
    "vetoed",
    "evaluated",
    "approved",
    "rejected",
    "pending_human_approval",
    "placed",
    "failed",
]

LogLevel = Literal["info", "warn", "error", "critical"]


class Event(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    service: str
    level: LogLevel
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: float
    idempotency_key: str | None = None


class Candidate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    ticker: str
    direction: Literal["long_call", "long_put"]
    status: CandidateStatus
    created_ts: float
    updated_ts: float
    indicators_json: dict[str, Any] = Field(default_factory=dict)
    veto_trace_json: dict[str, Any] = Field(default_factory=dict)
    llm_decision_json: dict[str, Any] = Field(default_factory=dict)
    human_decision: str | None = None
    human_decision_ts: float | None = None
    order_id: str | None = None


class Watchlist(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    date: str
    tickers: list[str] = Field(default_factory=list)
    per_ticker_overrides: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    created_ts: float
    created_by: Literal["manual", "auto_carry_forward", "system"]


class StrategyConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str
    settings: dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    created_ts: float
    updated_ts: float


class Position(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    candidate_id: int | None = None
    ticker: str
    contract_symbol: str
    side: Literal["long", "short"]
    quantity: int
    entry_price: Decimal
    entry_ts: float
    exit_price: Decimal | None = None
    exit_ts: float | None = None
    exit_reason: str | None = None
    pnl: Decimal | None = None
    status: Literal["open", "closed"]
    # Extended in migration 0006 — defaults keep prior callers working.
    entry_candidate_id: int | None = None
    exit_candidate_id: int | None = None
    strategy_name: str = "long_options_momentum"
    entry_iv: Decimal | None = None
    entry_delta: Decimal | None = None
    entry_dte: int | None = None
