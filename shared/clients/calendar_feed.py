"""Calendar feed: economic + earnings events. Abstract base + Pydantic model."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

EventType = Literal["economic", "earnings"]
ImpactLevel = Literal["low", "medium", "high", "unknown"]


class CalendarEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: EventType
    ticker: str | None = None
    event_name: str
    event_datetime_utc: datetime
    impact: ImpactLevel = "unknown"
    source: str = "finnhub"
    payload: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hours_until(self) -> Decimal:
        delta = self.event_datetime_utc - datetime.now(UTC)
        return Decimal(str(round(delta.total_seconds() / 3600, 4)))


class CalendarFeed(ABC):
    """Source of upcoming economic + earnings events."""

    @abstractmethod
    async def fetch_economic_calendar(
        self, start: date, end: date
    ) -> list[CalendarEvent]: ...

    @abstractmethod
    async def fetch_earnings_calendar(
        self, start: date, end: date, tickers: list[str] | None = None
    ) -> list[CalendarEvent]: ...

    @abstractmethod
    async def health_check(self) -> bool: ...
