"""Monitor service entry: AsyncIOScheduler firing exit-signal cycles every
5 minutes during 09:30-15:55 ET on weekdays. Mirrors the scanner bootstrap.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from services.monitor.cycle import run_monitor_cycle
from shared.clients.factory import make_halt_feed, make_market_data_client
from shared.config import settings
from shared.db import get_connection, run_migrations
from shared.events import emit
from shared.strategy.exit_settings import ExitSettings
from shared.util.dates import is_trading_day, today_et

SERVICE_NAME = "monitor"
ET = ZoneInfo("America/New_York")


def _within_window(start_str: str, end_str: str) -> bool:
    now_et = datetime.now(ET).time()
    start = datetime.strptime(start_str, "%H:%M").time()
    end = datetime.strptime(end_str, "%H:%M").time()
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

    halt_feed = make_halt_feed(settings)
    healthy = await client.health_check()
    if not healthy:
        return False, None

    exit_settings = ExitSettings()

    async def _monitor_tick() -> None:
        if not is_trading_day(today_et()):
            return
        if not _within_window(
            exit_settings.monitor_window_start_et,
            exit_settings.monitor_window_end_et,
        ):
            return
        conn = get_connection()
        try:
            await run_monitor_cycle(client, halt_feed, conn, exit_settings)
        except Exception as e:
            emit(
                SERVICE_NAME,
                "error",
                "monitor_cycle_failed",
                {"error": str(e)[:300], "error_type": type(e).__name__},
            )
        finally:
            conn.close()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _monitor_tick,
        IntervalTrigger(minutes=exit_settings.monitor_cadence_minutes),
        id="monitor_cycle",
        replace_existing=True,
    )
    scheduler.start()

    emit(
        SERVICE_NAME,
        "info",
        "service_started",
        {
            "client_type": settings.DATA_CLIENT,
            "cadence_minutes": exit_settings.monitor_cadence_minutes,
            "monitor_window": (
                f"{exit_settings.monitor_window_start_et}-"
                f"{exit_settings.monitor_window_end_et} ET"
            ),
            "monitor_enabled": exit_settings.monitor_enabled,
            "scheduler_jobs": [j.id for j in scheduler.get_jobs()],
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
