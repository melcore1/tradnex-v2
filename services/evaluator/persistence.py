"""Evaluator persistence: atomic claim, hydrate full candidate, persist
llm_evaluations row, persist selected_contract."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime
from typing import Any

from shared.analytics.full_analysis import FullAnalysis
from shared.analytics.options.full_options_analysis import FullOptionsAnalysis
from shared.analytics.regime import RegimeState
from shared.clients.exa_news import ExaArticle
from shared.schemas.market import OptionContract
from shared.strategy.base import (
    Candidate,
    EntryCandidate,
    ExitCandidate,
    RuleTrace,
)
from shared.strategy.exit_signals.base import ExitSignalTrace


class EvaluatorCandidateNotFoundError(LookupError):
    """No candidates row for the given id."""


async def claim_candidate_for_llm_eval(
    conn: sqlite3.Connection, candidate_id: int
) -> bool:
    """Atomically transition pending_llm_evaluation → processing_llm_evaluation.

    Returns True if THIS caller won the claim. False means somebody else
    already moved the candidate (worker race or status-changed externally).
    """
    cur = conn.execute(
        "UPDATE candidates SET status = 'processing_llm_evaluation', "
        "updated_ts = ? WHERE id = ? AND status = 'pending_llm_evaluation'",
        (time.time(), candidate_id),
    )
    conn.commit()
    return cur.rowcount == 1


async def load_full_candidate(
    conn: sqlite3.Connection, candidate_id: int
) -> Candidate:
    """Hydrate the full EntryCandidate or ExitCandidate from the candidates
    row + JSON columns."""
    row = conn.execute(
        "SELECT id, ticker, direction, status, candidate_kind, strategy_name, "
        "rule_trace_json, regime_snapshot_json, overrides_applied_json, "
        "shortlist_json, full_analysis_json, options_analysis_json, "
        "position_id, created_ts, selected_contract_json "
        "FROM candidates WHERE id = ?",
        (candidate_id,),
    ).fetchone()
    if row is None:
        raise EvaluatorCandidateNotFoundError(
            f"Candidate #{candidate_id} not found"
        )

    if row["candidate_kind"] == "entry":
        return _row_to_entry(row)
    return _row_to_exit(row)


def _row_to_entry(row: sqlite3.Row) -> EntryCandidate:
    rule_trace = RuleTrace.model_validate_json(row["rule_trace_json"])
    full_analysis = FullAnalysis.model_validate_json(row["full_analysis_json"])
    options_analysis: FullOptionsAnalysis | None = None
    if row["options_analysis_json"]:
        options_analysis = FullOptionsAnalysis.model_validate_json(
            row["options_analysis_json"]
        )
    regime = RegimeState.model_validate_json(row["regime_snapshot_json"])
    overrides = json.loads(row["overrides_applied_json"] or "{}")
    shortlist: list[OptionContract] | None = None
    if row["shortlist_json"]:
        shortlist = [
            OptionContract.model_validate(item)
            for item in json.loads(row["shortlist_json"])
        ]
    selected: OptionContract | None = None
    if row["selected_contract_json"]:
        selected = OptionContract.model_validate_json(
            row["selected_contract_json"]
        )
    confidence = rule_trace.confidence_label
    if confidence == "VETO":
        # Defensive: a VETO entry shouldn't reach the evaluator. Treat as WEAK.
        confidence = "WEAK"
    sizing_mult = overrides.get("sizing_multiplier")
    if sizing_mult is None:
        sizing_mult = 1
    max_premium = overrides.get("max_premium", 500)
    return EntryCandidate(
        ticker=row["ticker"],
        direction=row["direction"],
        strategy_name=row["strategy_name"] or "long_options_momentum",
        rule_trace=rule_trace,
        full_analysis=full_analysis,
        options_analysis=options_analysis,
        regime=regime,
        overrides_applied=overrides,
        confidence=confidence,  # type: ignore[arg-type]
        sizing_multiplier=sizing_mult,  # type: ignore[arg-type]
        max_premium=max_premium,  # type: ignore[arg-type]
        shortlist=shortlist,
        selected_contract=selected,
        timestamp=datetime.fromtimestamp(float(row["created_ts"]), tz=UTC),
    )


def _row_to_exit(row: sqlite3.Row) -> ExitCandidate:
    """Reconstruct ExitCandidate. Phase 3.5 stores signal_trace in
    rule_trace_json column and routing flags in overrides_applied_json."""
    signal_trace = ExitSignalTrace.model_validate_json(row["rule_trace_json"])
    overrides = json.loads(row["overrides_applied_json"] or "{}")
    return ExitCandidate(
        position_id=int(row["position_id"]),
        ticker=row["ticker"],
        exit_signal_type="soft_setup_invalidated",  # type: ignore[arg-type]
        is_auto_close=bool(overrides.get("is_auto_close", False)),
        needs_claude=bool(overrides.get("needs_claude", False)),
        auto_close_reason=overrides.get("auto_close_reason"),
        triggered_signals=overrides.get("triggered_signals", []),
        signal_trace=signal_trace,
        pnl_pct=signal_trace.pnl_pct,
        pnl_dollars=signal_trace.pnl_dollars,
        dte_remaining=signal_trace.dte_remaining,
        timestamp=datetime.fromtimestamp(float(row["created_ts"]), tz=UTC),
    )


async def persist_llm_evaluation(
    conn: sqlite3.Connection,
    *,
    candidate_id: int,
    prompt_version_id: int,
    prompt_template_name: str,
    full_prompt_text: str,
    raw_response_text: str,
    parsed_response_json: str,
    decision: str,
    confidence: float | None,
    reasoning: str,
    exa_articles: list[ExaArticle] | None,
    elapsed_ms: int,
    model_used: str,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
    error: str | None = None,
) -> int:
    articles_json: str | None
    if exa_articles is None:
        articles_json = None
    else:
        articles_json = json.dumps(
            [a.model_dump(mode="json") for a in exa_articles],
            default=str,
        )
    cur = conn.execute(
        "INSERT INTO llm_evaluations ("
        "candidate_id, prompt_version_id, prompt_template_name, "
        "full_prompt_text, raw_response_text, parsed_response_json, "
        "decision, confidence, reasoning, exa_articles_json, "
        "elapsed_ms, model_used, fallback_used, fallback_reason, error, "
        "timestamp"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            candidate_id,
            prompt_version_id,
            prompt_template_name,
            full_prompt_text,
            raw_response_text,
            parsed_response_json,
            decision,
            confidence,
            reasoning,
            articles_json,
            elapsed_ms,
            model_used,
            1 if fallback_used else 0,
            fallback_reason,
            error,
            time.time(),
        ),
    )
    conn.commit()
    new_id = cur.lastrowid
    if new_id is None:
        raise RuntimeError("Failed to insert llm_evaluations row")
    return int(new_id)


async def persist_selected_contract(
    conn: sqlite3.Connection,
    candidate_id: int,
    contract: OptionContract,
) -> None:
    conn.execute(
        "UPDATE candidates SET selected_contract_json = ?, updated_ts = ? "
        "WHERE id = ?",
        (contract.model_dump_json(), time.time(), candidate_id),
    )
    conn.commit()


def fetch_pending_llm_candidate_ids(
    conn: sqlite3.Connection,
    *,
    age_threshold_seconds: int = 0,
) -> list[int]:
    cutoff = time.time() - age_threshold_seconds
    rows = conn.execute(
        "SELECT id FROM candidates "
        "WHERE status = 'pending_llm_evaluation' AND created_ts <= ? "
        "ORDER BY created_ts ASC",
        (cutoff,),
    ).fetchall()
    return [int(r["id"]) for r in rows]


def reset_stranded_processing(conn: sqlite3.Connection) -> int:
    """Revert any rows in 'processing_llm_evaluation' (e.g. after a service
    crash) back to 'pending_llm_evaluation' so they get picked up again.
    Returns the number reset."""
    cur = conn.execute(
        "UPDATE candidates SET status = 'pending_llm_evaluation', "
        "updated_ts = ? WHERE status = 'processing_llm_evaluation'",
        (time.time(),),
    )
    conn.commit()
    return int(cur.rowcount)


def fetch_recent_evaluations(
    conn: sqlite3.Connection,
    *,
    candidate_id: int | None = None,
    hours: int = 24,
    limit: int = 100,
) -> list[dict[str, Any]]:
    cutoff = time.time() - (hours * 3600)
    sql = (
        "SELECT id, candidate_id, prompt_version_id, prompt_template_name, "
        "decision, confidence, reasoning, elapsed_ms, model_used, "
        "fallback_used, fallback_reason, error, timestamp "
        "FROM llm_evaluations WHERE timestamp >= ?"
    )
    params: list[Any] = [cutoff]
    if candidate_id is not None:
        sql += " AND candidate_id = ?"
        params.append(candidate_id)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
