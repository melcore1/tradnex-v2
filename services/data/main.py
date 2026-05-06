import asyncio
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from shared.clients.factory import make_halt_feed, make_market_data_client
from shared.config import settings
from shared.db import get_connection, run_migrations
from shared.events import emit

SERVICE_NAME = "data"


async def _bootstrap() -> tuple[bool, AsyncIOScheduler | None]:
    applied = run_migrations()
    if applied:
        emit(SERVICE_NAME, "info", "migrations_applied", {"files": applied})

    client = make_market_data_client(settings)
    if settings.DATA_CLIENT == "mock":
        from shared.clients.mock_market_data import MockDataClient

        if isinstance(client, MockDataClient):
            seeded = client.seed_iv_history()
            if seeded:
                emit(SERVICE_NAME, "info", "mock_iv_history_seeded", {"rows": seeded})

    # Watchlist <-> universe drift check
    from shared.services.watchlist import validate_watchlist_universe_sync

    sync_conn = get_connection()
    try:
        drift = await validate_watchlist_universe_sync(sync_conn)
        if drift:
            emit(
                SERVICE_NAME,
                "warn",
                "watchlist_universe_drift",
                {"drift_tickers": drift},
            )
    finally:
        sync_conn.close()

    healthy = await client.health_check()
    if not healthy:
        return False, None

    halt_feed = make_halt_feed(settings)

    from services.data.correlation_task import run_correlation_task
    from services.data.halt_monitor_task import HaltMonitor
    from services.data.iv_snapshot_task import snapshot_iv_for_ticker

    halt_monitor = HaltMonitor(
        halt_feed,
        market_seconds=settings.HALT_POLL_MARKET_SECONDS,
        off_hours_seconds=settings.HALT_POLL_OFF_HOURS_SECONDS,
    )

    async def _halt_tick() -> None:
        try:
            await halt_monitor.tick()
        except Exception as e:
            emit(SERVICE_NAME, "error", "halt_monitor_tick_failed", {"error": str(e)[:200]})

    async def _iv_snapshot_job() -> None:
        from shared.clients.mock_market_data import DEFAULT_BASELINES

        for ticker in DEFAULT_BASELINES:
            try:
                await snapshot_iv_for_ticker(ticker, client)
            except Exception as e:
                emit(
                    SERVICE_NAME,
                    "error",
                    "iv_snapshot_failed",
                    {"ticker": ticker, "error": str(e)[:200]},
                )

    async def _correlation_job() -> None:
        conn = get_connection()
        try:
            await run_correlation_task(client, conn)
        except Exception as e:
            emit(SERVICE_NAME, "error", "correlation_task_failed", {"error": str(e)[:200]})
        finally:
            conn.close()

    async def _calendar_refresh_job() -> None:
        from services.data.calendar_refresh_task import refresh_calendar_cache
        from shared.clients.factory import make_calendar_client
        from shared.services.encryption import maybe_get_encryption
        from shared.services.universe import get_universe

        conn = get_connection()
        try:
            calendar_client = make_calendar_client(
                settings, conn=conn, encryption=maybe_get_encryption()
            )
            universe = await get_universe(conn)
            await refresh_calendar_cache(calendar_client, conn, universe)
        except Exception as e:
            emit(
                SERVICE_NAME,
                "error",
                "calendar_refresh_failed",
                {"error": str(e)[:300], "error_type": type(e).__name__},
            )
        finally:
            conn.close()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _halt_tick,
        IntervalTrigger(seconds=settings.HALT_POLL_MARKET_SECONDS),
        id="halt_monitor",
        replace_existing=True,
    )
    # 15:55 ET ≈ 19:55 UTC during DST
    scheduler.add_job(
        _iv_snapshot_job,
        CronTrigger(day_of_week="mon-fri", hour=19, minute=55),
        id="iv_snapshot",
        replace_existing=True,
    )
    # 02:00 ET ≈ 06:00 UTC during DST
    scheduler.add_job(
        _correlation_job,
        CronTrigger(hour=6, minute=0),
        id="correlation_nightly",
        replace_existing=True,
    )
    # 06:00 ET ≈ 10:00 UTC during DST
    scheduler.add_job(
        _calendar_refresh_job,
        CronTrigger(hour=10, minute=0),
        id="calendar_refresh_nightly",
        replace_existing=True,
    )
    scheduler.start()
    emit(
        SERVICE_NAME,
        "info",
        "service_started",
        {
            "client_type": settings.DATA_CLIENT,
            "halt_feed": settings.HALT_FEED,
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
