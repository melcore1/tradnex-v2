"""Rule-based fallback when Claude is unavailable, llm_enabled=False, or the
prompt was too large to send.

Outcomes match the LLM-success routing as closely as possible:
  - Entry: rule confidence (STRONG/MODERATE/WEAK) → pending_human_approval.
           Pick contract via `select_default_contract`. Always have a
           fallback decision (rule traces with VETO never reach Phase 5).
  - Exit: any URGENT triggered signal → CLOSE → pending_human_approval.
          Otherwise HOLD → status='held'. Always emit a `claude_evaluated`
          lifecycle event with `fallback=True` for visibility.
"""

from __future__ import annotations

import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict

from services.evaluator.persistence import (
    persist_llm_evaluation,
    persist_selected_contract,
)
from services.orchestrator.persistence import update_candidate_status
from shared.events import emit
from shared.schemas.market import OptionContract
from shared.services.positions import emit_lifecycle_event
from shared.services.prompts import get_active_prompt
from shared.strategy.base import Candidate, EntryCandidate, ExitCandidate
from shared.strategy.exit_signals.base import ExitSignalSeverity
from shared.strategy.long_options_momentum import select_default_contract
from shared.strategy.settings import EvaluatorSettings

SERVICE_NAME = "evaluator"


class EvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: int
    eval_id: int | None
    decision: str
    confidence: float | None
    new_status: str
    fallback: bool
    fallback_reason: str | None = None


def _decide_entry_fallback(
    candidate: EntryCandidate, cfg: EvaluatorSettings
) -> tuple[str, OptionContract | None, Literal["pending_human_approval"]]:
    decision = candidate.confidence  # STRONG | MODERATE | WEAK
    contract = select_default_contract(
        candidate.shortlist or [],
        (cfg.delta_target_range_low, cfg.delta_target_range_high),
    )
    return decision, contract, "pending_human_approval"


def _decide_exit_fallback(
    candidate: ExitCandidate,
) -> tuple[str, Literal["pending_human_approval", "held"]]:
    any_urgent = any(
        s.triggered
        and s.severity in (ExitSignalSeverity.URGENT, ExitSignalSeverity.AUTO_CLOSE)
        for s in candidate.signal_trace.signals
    )
    if any_urgent:
        return "CLOSE", "pending_human_approval"
    return "HOLD", "held"


async def run_fallback_evaluation(
    conn: sqlite3.Connection,
    candidate_id: int,
    candidate: Candidate,
    *,
    cfg: EvaluatorSettings,
    fallback_reason: str,
    full_prompt_text: str = "<not_built>",
) -> EvaluationResult:
    """Persist a fallback llm_evaluations row and transition the candidate.

    `prompt_version_id` is set to the currently-active prompt for the
    matching template (avoiding a nullable FK in the schema).
    """
    template_name: str
    if candidate.candidate_kind == "entry":
        template_name = "entry_evaluation"
    else:
        template_name = "exit_evaluation"

    active = await get_active_prompt(conn, template_name)  # type: ignore[arg-type]

    contract: OptionContract | None
    confidence: float | None = None
    new_status: str
    decision: str

    if candidate.candidate_kind == "entry":
        decision, contract, new_status = _decide_entry_fallback(candidate, cfg)
    else:
        decision, new_status = _decide_exit_fallback(candidate)
        contract = None

    eval_id = await persist_llm_evaluation(
        conn,
        candidate_id=candidate_id,
        prompt_version_id=active.id,
        prompt_template_name=template_name,
        full_prompt_text=full_prompt_text,
        raw_response_text="<fallback>",
        parsed_response_json="{}",
        decision=decision,
        confidence=confidence,
        reasoning=f"fallback: {fallback_reason}",
        exa_articles=[],
        elapsed_ms=0,
        model_used="fallback",
        fallback_used=True,
        fallback_reason=fallback_reason,
    )

    if candidate.candidate_kind == "entry" and contract is not None:
        await persist_selected_contract(conn, candidate_id, contract)

    await update_candidate_status(conn, candidate_id, new_status)

    if candidate.candidate_kind == "exit":
        await emit_lifecycle_event(
            conn,
            candidate.position_id,
            "claude_evaluated",
            payload={
                "decision": decision,
                "fallback": True,
                "reason": fallback_reason,
                "eval_id": eval_id,
            },
        )

    emit(
        SERVICE_NAME,
        "info",
        "fallback_evaluated",
        {
            "candidate_id": candidate_id,
            "kind": candidate.candidate_kind,
            "decision": decision,
            "reason": fallback_reason,
            "new_status": new_status,
        },
    )
    return EvaluationResult(
        candidate_id=candidate_id,
        eval_id=eval_id,
        decision=decision,
        confidence=confidence,
        new_status=new_status,
        fallback=True,
        fallback_reason=fallback_reason,
    )
