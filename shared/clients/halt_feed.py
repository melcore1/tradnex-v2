"""Trading halt feed: abstract interface and Halt model."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Halt(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    halt_time: datetime
    halt_reason: str
    halt_code: str
    resumption_time: datetime | None = None
    is_active: bool
    exchange: str = "NASDAQ"


class HaltFeed(ABC):
    """Source of trading halts. Mock + NASDAQ RSS implementations live as peers."""

    @abstractmethod
    async def get_active_halts(self) -> list[Halt]: ...

    @abstractmethod
    async def get_recent_halts(self, hours: int = 24) -> list[Halt]: ...

    @abstractmethod
    async def is_halted(self, ticker: str) -> bool: ...

    @abstractmethod
    async def health_check(self) -> bool: ...
