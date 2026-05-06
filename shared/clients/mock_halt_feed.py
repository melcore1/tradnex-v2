"""In-memory halt feed for dev and tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from shared.clients.halt_feed import Halt, HaltFeed


class MockHaltFeed(HaltFeed):
    def __init__(self) -> None:
        self._halts: list[Halt] = []

    def inject_halt(self, halt: Halt) -> None:
        self._halts.append(halt)

    def clear_halts(self) -> None:
        self._halts.clear()

    def resolve_halt(self, ticker: str, resumption_time: datetime) -> None:
        for i, h in enumerate(self._halts):
            if h.ticker == ticker.upper() and h.is_active:
                self._halts[i] = h.model_copy(
                    update={"is_active": False, "resumption_time": resumption_time}
                )
                return

    async def get_active_halts(self) -> list[Halt]:
        return [h for h in self._halts if h.is_active]

    async def get_recent_halts(self, hours: int = 24) -> list[Halt]:
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        return [h for h in self._halts if h.halt_time >= cutoff]

    async def is_halted(self, ticker: str) -> bool:
        ticker_u = ticker.upper()
        return any(h.is_active and h.ticker == ticker_u for h in self._halts)

    async def health_check(self) -> bool:
        return True
