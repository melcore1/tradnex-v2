"""Backup poller: catches candidates stuck in 'pending' for >5 min."""

from __future__ import annotations

from services.orchestrator.persistence import fetch_pending_candidate_ids
from services.orchestrator.process_candidate import process_candidate
from shared.events import emit
from shared.strategy.vetoes.base import VetoContext

SERVICE_NAME = "orchestrator"


async def poll_for_stragglers(
    ctx: VetoContext,
    *,
    stale_seconds: int = 300,
) -> int:
    """Process all candidates in 'pending' state created >stale_seconds ago.
    Returns the number processed."""
    ids = fetch_pending_candidate_ids(ctx.conn, stale_seconds=stale_seconds)
    if not ids:
        return 0
    processed = 0
    for cid in ids:
        try:
            await process_candidate(cid, ctx)
            processed += 1
        except Exception as e:
            emit(
                SERVICE_NAME,
                "error",
                "poller_process_error",
                {
                    "candidate_id": cid,
                    "error": str(e)[:200],
                    "error_type": type(e).__name__,
                },
            )
    if processed > 0:
        emit(
            SERVICE_NAME,
            "info",
            "poller_stragglers_processed",
            {"count": processed, "stale_seconds": stale_seconds},
        )
    return processed
