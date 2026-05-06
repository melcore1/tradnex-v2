"""Main orchestrator routing function. Idempotent and crash-safe."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from services.orchestrator.persistence import (
    load_candidate,
    persist_veto_trace,
    update_candidate_status,
)
from shared.events import emit
from shared.services.positions import emit_lifecycle_event
from shared.strategy.vetoes.base import VetoContext, VetoTrace
from shared.strategy.vetoes.runner import run_vetoes

SERVICE_NAME = "orchestrator"


class ProcessResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    candidate_id: int
    already_processed: bool
    new_status: str
    veto_trace: VetoTrace | None = None
    note: str | None = None


async def process_candidate(
    candidate_id: int,
    ctx: VetoContext,
) -> ProcessResult:
    """Run vetoes on a candidate, persist trace, transition status."""
    candidate = await load_candidate(ctx.conn, candidate_id)

    if candidate.status != "pending":
        return ProcessResult(
            candidate_id=candidate_id,
            already_processed=True,
            new_status=candidate.status,
            note="non-pending status; orchestrator no-op",
        )

    await update_candidate_status(ctx.conn, candidate_id, "processing_vetoes")

    try:
        trace = await run_vetoes(candidate, ctx)
        await persist_veto_trace(ctx.conn, trace)
    except Exception:
        # Revert to pending so the poller can retry. Re-raise so the caller
        # / safe_process_candidate logs the underlying exception.
        await update_candidate_status(ctx.conn, candidate_id, "pending")
        raise

    new_status: str
    if trace.any_failed:
        new_status = "vetoed"
        if candidate.candidate_kind == "exit" and candidate.position_id is not None:
            await emit_lifecycle_event(
                ctx.conn,
                candidate.position_id,
                "human_rejected",
                cycle_id=None,
                payload={
                    "reason": "orchestrator_veto",
                    "candidate_id": candidate_id,
                    "failed_vetoes": trace.failed_veto_names,
                },
            )
    elif candidate.candidate_kind == "exit" and candidate.is_auto_close:
        new_status = "pending_human_approval"
        if candidate.position_id is not None:
            await emit_lifecycle_event(
                ctx.conn,
                candidate.position_id,
                "monitor_evaluated",
                cycle_id=None,
                payload={
                    "route": "auto_close_to_human",
                    "candidate_id": candidate_id,
                },
            )
    else:
        new_status = "pending_llm_evaluation"

    await update_candidate_status(ctx.conn, candidate_id, new_status)
    emit(
        SERVICE_NAME,
        "info",
        "candidate_processed",
        {
            "candidate_id": candidate_id,
            "kind": candidate.candidate_kind,
            "ticker": candidate.ticker,
            "old_status": "pending",
            "new_status": new_status,
            "vetoes_failed": trace.failed_veto_names,
        },
    )
    # Phase 5: trigger the LLM evaluator immediately when we route the
    # candidate to LLM evaluation. Fire-and-forget; the standalone evaluator
    # service / poller catch anything that fails or races. The atomic claim
    # inside the queue ensures exactly-once processing.
    if new_status == "pending_llm_evaluation":
        import asyncio as _asyncio

        from services.orchestrator.evaluator_trigger import safe_evaluator_call

        _asyncio.create_task(safe_evaluator_call(candidate_id))
    return ProcessResult(
        candidate_id=candidate_id,
        already_processed=False,
        new_status=new_status,
        veto_trace=trace,
    )


async def safe_process_candidate(
    candidate_id: int,
    ctx_factory: Any,
) -> None:
    """Wrapper used by `asyncio.create_task` from scanner / monitor.

    `ctx_factory` is a zero-arg callable returning a fresh VetoContext (we
    don't share connections across coroutines in SQLite). Failures here
    leave the candidate in `pending` so the poller can retry later.
    """
    try:
        ctx = ctx_factory()
        await process_candidate(candidate_id, ctx)
    except Exception as e:
        emit(
            SERVICE_NAME,
            "error",
            "candidate_processing_failed",
            {
                "candidate_id": candidate_id,
                "error": str(e)[:300],
                "error_type": type(e).__name__,
            },
        )
