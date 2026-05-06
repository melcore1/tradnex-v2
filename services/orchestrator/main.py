"""Orchestrator service entry: AsyncIOScheduler running the backup poller
every 5 min. Scanner / monitor trigger the orchestrator inline via
`asyncio.create_task`; the poller catches stragglers."""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from services.orchestrator.poller import poll_for_stragglers
from shared.clients.factory import make_halt_feed
from shared.config import settings
from shared.db import get_connection, run_migrations
from shared.events import emit
from shared.services.calendar_service import CalendarService
from shared.strategy.vetoes.base import VetoContext, VetoSettings

SERVICE_NAME = "orchestrator"


async def _bootstrap() -> AsyncIOScheduler:
    applied = run_migrations()
    if applied:
        emit(SERVICE_NAME, "info", "migrations_applied", {"files": applied})

    halt_feed = make_halt_feed(settings)

    async def _poller_tick() -> None:
        conn = get_connection()
        try:
            ctx = VetoContext(
                conn=conn,
                calendar_service=CalendarService(conn),
                halt_feed=halt_feed,
                settings=VetoSettings(),
                current_time_utc=datetime.now(UTC),
            )
            await poll_for_stragglers(ctx)
        except Exception as e:
            emit(
                SERVICE_NAME,
                "error",
                "poller_tick_failed",
                {"error": str(e)[:300], "error_type": type(e).__name__},
            )
        finally:
            conn.close()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _poller_tick,
        IntervalTrigger(minutes=5),
        id="orchestrator_poller",
        replace_existing=True,
    )
    scheduler.start()

    emit(
        SERVICE_NAME,
        "info",
        "service_started",
        {
            "environment": settings.ENVIRONMENT,
            "scheduler_jobs": [j.id for j in scheduler.get_jobs()],
        },
    )
    return scheduler


def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    scheduler = loop.run_until_complete(_bootstrap())

    def _shutdown(*_: object) -> None:
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
