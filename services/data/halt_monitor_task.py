"""Halt monitor: periodically polls HaltFeed, emits events on new halts."""

from __future__ import annotations

from datetime import UTC, datetime, time

from shared.clients.halt_feed import HaltFeed
from shared.events import emit

SERVICE_NAME = "data"


def _is_market_hours_now() -> bool:
    now = datetime.now(UTC)
    if now.weekday() >= 5:
        return False
    return time(13, 30) <= now.time() <= time(20, 0)


class HaltMonitor:
    """Stateful monitor: deduplicates halt events by (ticker, halt_time)."""

    def __init__(
        self,
        feed: HaltFeed,
        market_seconds: int = 30,
        off_hours_seconds: int = 300,
    ) -> None:
        self._feed = feed
        self._market_seconds = market_seconds
        self._off_hours_seconds = off_hours_seconds
        self._seen: set[tuple[str, str]] = set()
        self._last_tick: datetime | None = None

    async def tick(self) -> int:
        """One poll cycle. Self-rate-limits during off-hours."""
        now = datetime.now(UTC)
        if self._last_tick is not None:
            elapsed = (now - self._last_tick).total_seconds()
            min_elapsed = (
                self._market_seconds if _is_market_hours_now() else self._off_hours_seconds
            )
            if elapsed < min_elapsed:
                return 0
        self._last_tick = now

        active = await self._feed.get_active_halts()
        new_count = 0
        for halt in active:
            key = (halt.ticker, halt.halt_time.isoformat())
            if key in self._seen:
                continue
            self._seen.add(key)
            emit(
                SERVICE_NAME,
                "warn",
                "halt_detected",
                {
                    "ticker": halt.ticker,
                    "code": halt.halt_code,
                    "reason": halt.halt_reason,
                    "halt_time": halt.halt_time.isoformat(),
                    "exchange": halt.exchange,
                },
                idempotency_key=f"halt:{halt.ticker}:{halt.halt_time.isoformat()}",
            )
            new_count += 1
        return new_count
