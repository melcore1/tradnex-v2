"""Fire-and-forget evaluator trigger from inside the orchestrator's
`process_candidate`. Mirrors the `_safe_orchestrator_call` pattern in
scanner/monitor cycles — opens a fresh DB connection, runs the
evaluator, swallows + emits any exception so the orchestrator's caller
isn't affected.

The atomic claim inside the evaluator's queue makes this safe even when
multiple paths race (immediate trigger + queue worker + 5-min poller).
"""

from __future__ import annotations

from shared.events import emit

SERVICE_NAME = "orchestrator"


async def safe_evaluator_call(candidate_id: int) -> None:
    """Run the evaluator on a single candidate. Best-effort — on failure,
    the candidate stays in `pending_llm_evaluation` and the standalone
    evaluator service / poller catches it later."""
    try:
        from services.evaluator.evaluate import evaluate_candidate
        from services.evaluator.persistence import claim_candidate_for_llm_eval
        from shared.clients.factory import make_claude_client, make_exa_client
        from shared.config import settings as cfg
        from shared.db import get_connection
        from shared.services.encryption import maybe_get_encryption
        from shared.strategy.settings import StrategySettings

        evaluator_cfg = StrategySettings().evaluator
        claude = make_claude_client(cfg)

        # Build the Exa client with credentials store lookup.
        creds_conn = get_connection()
        try:
            exa = make_exa_client(
                cfg, conn=creds_conn, encryption=maybe_get_encryption()
            )
        finally:
            creds_conn.close()

        claim_conn = get_connection()
        try:
            claimed = await claim_candidate_for_llm_eval(claim_conn, candidate_id)
        finally:
            claim_conn.close()
        if not claimed:
            # Either status flipped externally (poller already grabbed it)
            # or the candidate isn't in pending_llm_evaluation. Skip.
            return

        worker_conn = get_connection()
        try:
            await evaluate_candidate(
                candidate_id, worker_conn, claude, exa, evaluator_cfg
            )
        finally:
            worker_conn.close()
    except Exception as e:
        emit(
            SERVICE_NAME,
            "error",
            "evaluator_trigger_failed",
            {
                "candidate_id": candidate_id,
                "error": str(e)[:300],
                "error_type": type(e).__name__,
            },
        )
