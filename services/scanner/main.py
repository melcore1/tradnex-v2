"""Scanner service entry point.

Runs an AsyncIOScheduler that fires one scan cycle every 10 minutes during
the trading window (defaults: 09:45-15:00 ET, weekdays only). Per-tick
the worker exits early on weekends, US holidays, and outside the window.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from services.scanner.cycle import run_scan_cycle
from shared.clients.factory import make_market_data_client
from shared.config import settings
from shared.db import get_connection, run_migrations
from shared.events import emit
from shared.strategy.long_options_momentum import LongOptionsMomentum
from shared.strategy.settings import MarketWindow
from shared.util.dates import is_trading_day, today_et

SERVICE_NAME = "scanner"
ET = ZoneInfo("America/New_York")


def _within_window(window: MarketWindow) -> bool:
    """True when current ET time is between scanner_start and scanner_end."""
    now_et = datetime.now(ET).time()
    start = datetime.strptime(window.scanner_start, "%H:%M").time()
    end = datetime.strptime(window.scanner_end, "%H:%M").time()
    return start <= now_et <= end


async def _bootstrap() -> tuple[bool, AsyncIOScheduler | None]:
    applied = run_migrations()
    if applied:
        emit(SERVICE_NAME, "info", "migrations_applied", {"files": applied})

    client = make_market_data_client(settings)
    if settings.DATA_CLIENT == "mock":
        from shared.clients.mock_market_data import MockDataClient

        if isinstance(client, MockDataClient):
            client.seed_iv_history()

    healthy = await client.health_check()
    if not healthy:
        return False, None

    strategy = LongOptionsMomentum()
    window = strategy.settings.market_window

    async def _scan_tick() -> None:
        if not is_trading_day(today_et()):
            return
        if not _within_window(window):
            return
        conn = get_connection()
        try:
            await run_scan_cycle(client, conn, strategy)
        except Exception as e:
            emit(
                SERVICE_NAME,
                "error",
                "scan_cycle_failed",
                {"error": str(e)[:300], "error_type": type(e).__name__},
            )
        finally:
            conn.close()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _scan_tick,
        IntervalTrigger(minutes=10),
        id="scan_cycle",
        replace_existing=True,
    )
    scheduler.start()

    emit(
        SERVICE_NAME,
        "info",
        "service_started",
        {
            "client_type": settings.DATA_CLIENT,
            "scanner_window": f"{window.scanner_start}-{window.scanner_end} ET",
            "scheduler_jobs": [j.id for j in scheduler.get_jobs()],
            "healthy": healthy,
        },
    )
    return healthy, scheduler


def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    healthy, scheduler = loop.run_until_complete(_bootstrap())
    if not healthy:
        emit(SERVICE_NAME, "error", "health_check_failed", {})
        if scheduler:
            scheduler.shutdown(wait=False)
        sys.exit(1)

    def _shutdown(*_: object) -> None:
        if scheduler:
            scheduler.shutdown(wait=False)
        loop.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    try:
        loop.run_forever()
    finally:
        loop.close()


if __name__ == "__main__":
    main()
