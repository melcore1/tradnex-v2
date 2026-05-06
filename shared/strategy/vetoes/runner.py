"""Veto runner: dispatches the appropriate veto set, traps exceptions."""

from __future__ import annotations

from shared.events import emit
from shared.strategy.vetoes.base import (
    OrchestratorCandidate,
    VetoContext,
    VetoResult,
    VetoTrace,
)
from shared.strategy.vetoes.entry import ENTRY_VETOES
from shared.strategy.vetoes.exit import EXIT_VETOES

SERVICE_NAME = "orchestrator"


async def run_vetoes(
    candidate: OrchestratorCandidate,
    ctx: VetoContext,
) -> VetoTrace:
    """Run the entry or exit veto set. All vetoes run; per-veto exceptions
    are caught and converted into failed=False results so the orchestrator
    never crashes due to a buggy veto."""
    if candidate.candidate_kind == "entry":
        vetoes = ENTRY_VETOES
        veto_set: str = "entry"
    else:
        vetoes = EXIT_VETOES
        veto_set = "exit"

    results: list[VetoResult] = []
    for veto in vetoes:
        try:
            result = await veto(candidate, ctx)
        except Exception as e:
            emit(
                SERVICE_NAME,
                "error",
                "veto_exception",
                {
                    "veto": veto.__name__,
                    "candidate_id": candidate.id,
                    "error": str(e)[:300],
                    "error_type": type(e).__name__,
                },
            )
            result = VetoResult(
                name=veto.__name__,
                description="veto raised exception",
                failed=False,
                failure_reason=None,
                details={"error": str(e)[:300], "error_type": type(e).__name__},
            )
        results.append(result)

    any_failed = any(r.failed for r in results)
    return VetoTrace(
        candidate_id=candidate.id,
        veto_set=veto_set,  # type: ignore[arg-type]
        timestamp=ctx.current_time_utc,
        results=results,
        any_failed=any_failed,
        failed_veto_names=[r.name for r in results if r.failed],
    )
