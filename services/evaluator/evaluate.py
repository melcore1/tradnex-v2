"""Main evaluation flow: load candidate, build prompt, call Claude, persist."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from services.evaluator.fallback import (
    EvaluationResult,
    run_fallback_evaluation,
)
from services.evaluator.persistence import (
    load_full_candidate,
    persist_llm_evaluation,
    persist_selected_contract,
)
from services.orchestrator.persistence import update_candidate_status
from shared.clients.claude_cli import (
    ClaudeCliClient,
    ClaudeResponseInvalidError,
    ClaudeUnavailableError,
)
from shared.clients.exa_news import ExaArticle, ExaClient
from shared.clients.mock_claude_cli import MockClaudeCliClient
from shared.events import emit
from shared.schemas.market import OptionContract
from shared.services.positions import emit_lifecycle_event
from shared.services.prompt_builder import (
    PromptTooLargeError,
    build_entry_prompt,
    build_exit_prompt,
)
from shared.services.prompts import PromptVersion
from shared.strategy.base import Candidate, EntryCandidate
from shared.strategy.settings import EvaluatorSettings

SERVICE_NAME = "evaluator"


def _route_after_claude(
    candidate: Candidate, decision: str
) -> str:
    if candidate.candidate_kind == "entry":
        if decision == "VETO":
            return "rejected_by_llm"
        # STRONG | MODERATE | WEAK
        return "pending_human_approval"
    # Exit:
    if decision in ("CLOSE", "CLOSE_PARTIAL"):
        return "pending_human_approval"
    # HOLD
    return "held"


def _extract_contract_pick(
    candidate: EntryCandidate,
    parsed: dict[str, Any],
) -> OptionContract | None:
    """Find the chosen contract by symbol in the candidate's shortlist."""
    sel = parsed.get("selected_contract")
    if not isinstance(sel, dict):
        return None
    symbol = sel.get("symbol")
    if not symbol or not candidate.shortlist:
        return None
    for c in candidate.shortlist:
        if c.symbol == symbol:
            return c
    return None


async def evaluate_candidate(
    candidate_id: int,
    conn: sqlite3.Connection,
    claude: ClaudeCliClient | MockClaudeCliClient,
    exa: ExaClient,
    cfg: EvaluatorSettings,
) -> EvaluationResult:
    """Run a full evaluation pass. Caller must have already claimed the
    candidate (status = 'processing_llm_evaluation')."""
    from shared.services.runtime_toggles import get_toggle

    candidate = await load_full_candidate(conn, candidate_id)

    # LLM bypass: runtime toggle wins over compile-time default. Skip
    # Claude and run the rule-based fallback when either is False.
    runtime_llm_enabled = get_toggle(conn, "llm_enabled", default=cfg.llm_enabled)
    if not runtime_llm_enabled or not cfg.llm_enabled:
        return await run_fallback_evaluation(
            conn, candidate_id, candidate,
            cfg=cfg, fallback_reason="llm_disabled",
        )

    # Build the prompt (pre-fetches Exa news + calendar context).
    prompt: str
    version: PromptVersion
    articles: list[ExaArticle]
    try:
        if candidate.candidate_kind == "entry":
            prompt, version, articles = await build_entry_prompt(
                candidate, conn, exa, cfg
            )
        else:
            prompt, version, articles = await build_exit_prompt(
                candidate, conn, exa, cfg
            )
    except PromptTooLargeError as e:
        return await run_fallback_evaluation(
            conn, candidate_id, candidate,
            cfg=cfg,
            fallback_reason=f"prompt_too_large:{e.rendered_len}",
        )

    # Call Claude.
    t0 = time.time()
    try:
        response = await claude.evaluate(
            prompt, expected_schema=version.response_schema
        )
    except ClaudeUnavailableError as e:
        return await run_fallback_evaluation(
            conn, candidate_id, candidate,
            cfg=cfg,
            fallback_reason=f"claude_unavailable:{str(e)[:200]}",
            full_prompt_text=prompt,
        )
    except ClaudeResponseInvalidError as e:
        return await run_fallback_evaluation(
            conn, candidate_id, candidate,
            cfg=cfg,
            fallback_reason=f"invalid_response:{str(e)[:200]}",
            full_prompt_text=prompt,
        )

    elapsed_ms = int((time.time() - t0) * 1000)
    parsed = response.parsed_json
    decision = str(parsed.get("decision", "VETO"))
    confidence_raw = parsed.get("confidence")
    confidence: float | None = (
        float(confidence_raw) if isinstance(confidence_raw, int | float) else None
    )
    reasoning = str(parsed.get("reasoning", ""))

    eval_id = await persist_llm_evaluation(
        conn,
        candidate_id=candidate_id,
        prompt_version_id=version.id,
        prompt_template_name=version.template_name,
        full_prompt_text=prompt,
        raw_response_text=response.raw_text,
        parsed_response_json=json.dumps(parsed, default=str),
        decision=decision,
        confidence=confidence,
        reasoning=reasoning,
        exa_articles=articles,
        elapsed_ms=elapsed_ms,
        model_used=response.model,
        fallback_used=False,
    )

    if candidate.candidate_kind == "entry":
        contract_pick = _extract_contract_pick(candidate, parsed)
        if contract_pick is not None:
            await persist_selected_contract(conn, candidate_id, contract_pick)

    new_status = _route_after_claude(candidate, decision)
    await update_candidate_status(conn, candidate_id, new_status)

    if candidate.candidate_kind == "exit":
        await emit_lifecycle_event(
            conn,
            candidate.position_id,
            "claude_evaluated",
            payload={
                "decision": decision,
                "confidence": confidence,
                "eval_id": eval_id,
                "fallback": False,
            },
        )

    emit(
        SERVICE_NAME,
        "info",
        "candidate_evaluated",
        {
            "candidate_id": candidate_id,
            "kind": candidate.candidate_kind,
            "decision": decision,
            "new_status": new_status,
            "elapsed_ms": elapsed_ms,
            "model": response.model,
        },
    )

    return EvaluationResult(
        candidate_id=candidate_id,
        eval_id=eval_id,
        decision=decision,
        confidence=confidence,
        new_status=new_status,
        fallback=False,
    )
