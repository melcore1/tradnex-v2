"""Evaluator service entry: bootstrap + worker loop + APScheduler poller.

Bootstrap order:
  1. Apply migrations (no-op if already applied).
  2. Reset any stranded `processing_llm_evaluation` rows back to
     `pending_llm_evaluation` (recovery from a crashed process).
  3. Re-enqueue all `pending_llm_evaluation` candidates ordered by
     `created_ts`.
  4. Start the APScheduler poller (5-min interval).
  5. Run the worker loop forever.
"""

from __future__ import annotations

import asyncio
import signal
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from services.evaluator.persistence import (
    fetch_pending_llm_candidate_ids,
    reset_stranded_processing,
)
from services.evaluator.poller import poll_for_stragglers
from services.evaluator.queue import EvaluationQueue
from shared.clients.factory import make_claude_client, make_exa_client
from shared.config import settings
from shared.db import get_connection, run_migrations
from shared.events import emit
from shared.strategy.settings import EvaluatorSettings, StrategySettings

SERVICE_NAME = "evaluator"


async def bootstrap_evaluator(cfg: EvaluatorSettings) -> EvaluationQueue:
    """Reset stranded rows, build the queue, rehydrate from DB."""
    conn = get_connection()
    try:
        reset_count = reset_stranded_processing(conn)
        if reset_count > 0:
            emit(
                SERVICE_NAME,
                "info",
                "reset_stranded",
                {"count": reset_count},
            )
        pending_ids = fetch_pending_llm_candidate_ids(conn)
    finally:
        conn.close()

    queue = EvaluationQueue(
        max_concurrent=cfg.max_concurrent_evaluations,
    )
    for cid in pending_ids:
        await queue.enqueue(cid)
    emit(
        SERVICE_NAME,
        "info",
        "rehydrated",
        {"count": len(pending_ids)},
    )
    return queue


async def _bootstrap() -> tuple[AsyncIOScheduler, EvaluationQueue]:
    applied = run_migrations()
    if applied:
        emit(SERVICE_NAME, "info", "migrations_applied", {"files": applied})

    cfg = StrategySettings().evaluator
    queue = await bootstrap_evaluator(cfg)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        partial(poll_for_stragglers, queue, cfg),
        IntervalTrigger(seconds=cfg.poll_interval_seconds),
        id="evaluator_poller",
        replace_existing=True,
    )
    scheduler.start()

    emit(
        SERVICE_NAME,
        "info",
        "service_started",
        {
            "environment": settings.ENVIRONMENT,
            "claude_client": settings.CLAUDE_CLIENT,
            "model": cfg.claude_model,
            "max_concurrent": cfg.max_concurrent_evaluations,
            "scheduler_jobs": [j.id for j in scheduler.get_jobs()],
        },
    )
    return scheduler, queue


async def _run_forever(queue: EvaluationQueue) -> None:
    """Worker loop pulling from the queue."""
    from shared.services.encryption import maybe_get_encryption

    cfg = StrategySettings().evaluator
    claude = make_claude_client(settings)
    # Resolve the Exa API key once at startup. The client stores the key
    # for its lifetime; if credentials change while the worker is running,
    # the operator restarts the service (Phase 8c will add hot-reload).
    conn = get_connection()
    try:
        exa = make_exa_client(
            settings, conn=conn, encryption=maybe_get_encryption()
        )
    finally:
        conn.close()
    while True:
        did_work = await queue.process_one(
            claude=claude, exa=exa, cfg=cfg,
        )
        if not did_work:
            await asyncio.sleep(1)


def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    scheduler, queue = loop.run_until_complete(_bootstrap())

    def _shutdown(*_: object) -> None:
        scheduler.shutdown(wait=False)
        loop.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    try:
        loop.run_until_complete(_run_forever(queue))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
