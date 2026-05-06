"""Backup poller: scans for stranded `pending_llm_evaluation` rows and
re-enqueues them. Runs every poll_interval_seconds (default 5 min).

Belt-and-braces — the orchestrator triggers immediately on transition,
but a crashed task or unclean shutdown can leave a row stranded. The
poller is idempotent because the queue's `enqueue` is idempotent and the
atomic claim handles the race.
"""

from __future__ import annotations

from services.evaluator.persistence import fetch_pending_llm_candidate_ids
from services.evaluator.queue import EvaluationQueue
from shared.db import get_connection
from shared.events import emit
from shared.strategy.settings import EvaluatorSettings

SERVICE_NAME = "evaluator"


async def poll_for_stragglers(
    queue: EvaluationQueue, cfg: EvaluatorSettings
) -> int:
    """Find candidates in pending_llm_evaluation older than the threshold,
    enqueue them. Returns the count enqueued."""
    conn = get_connection()
    try:
        ids = fetch_pending_llm_candidate_ids(
            conn, age_threshold_seconds=cfg.poll_age_threshold_seconds
        )
    finally:
        conn.close()
    for cid in ids:
        await queue.enqueue(cid)
    if ids:
        emit(
            SERVICE_NAME,
            "info",
            "poller_stragglers_enqueued",
            {"count": len(ids)},
        )
    return len(ids)
