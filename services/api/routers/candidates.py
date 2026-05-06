"""/api/candidates — list, get, full-context, approve, reject."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status

from services.api.deps import DB, CurrentUser
from services.api.schemas import (
    ApproveRequest,
    CandidateActionResponse,
    CandidateDetail,
    CandidateSummary,
    RejectRequest,
)
from services.evaluator.persistence import fetch_recent_evaluations
from services.orchestrator.persistence import fetch_latest_veto_trace
from shared.events import emit
from shared.services.positions import get_position_lifecycle

router = APIRouter()


def _summary_text(row: dict[str, Any]) -> str:
    pieces = [f"{row['ticker']} {row['direction']}"]
    if row.get("candidate_kind") == "exit":
        pieces.append("EXIT")
    pieces.append(f"status={row['status']}")
    return " ".join(pieces)


@router.get("", response_model=list[CandidateSummary])
async def list_candidates(
    db: DB,
    user: CurrentUser,
    since_hours: int = Query(24, ge=1, le=720),
    limit: int = Query(50, ge=1, le=500),
    candidate_status: str | None = Query(None, alias="status"),
    kind: Literal["entry", "exit"] | None = None,
) -> list[CandidateSummary]:
    """List candidates filtered by time window, status, kind."""
    cutoff = time.time() - since_hours * 3600
    sql = (
        "SELECT id, ticker, direction, status, candidate_kind, created_ts, "
        "rule_trace_json FROM candidates WHERE created_ts >= ?"
    )
    params: list[Any] = [cutoff]
    if candidate_status is not None:
        sql += " AND status = ?"
        params.append(candidate_status)
    if kind is not None:
        sql += " AND candidate_kind = ?"
        params.append(kind)
    sql += " ORDER BY created_ts DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(sql, params).fetchall()
    out: list[CandidateSummary] = []
    for r in rows:
        confidence: str | None = None
        if r["rule_trace_json"] and r["candidate_kind"] == "entry":
            try:
                trace = json.loads(r["rule_trace_json"])
                confidence = trace.get("confidence_label")
            except json.JSONDecodeError:
                pass
        rd = dict(r)
        out.append(
            CandidateSummary(
                id=int(r["id"]),
                candidate_kind=r["candidate_kind"],
                ticker=r["ticker"],
                direction=r["direction"],
                status=r["status"],
                confidence=confidence,
                created_ts=datetime.fromtimestamp(float(r["created_ts"]), tz=UTC),
                summary_text=_summary_text(rd),
            )
        )
    return out


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _load_candidate_row(db: Any, candidate_id: int) -> dict[str, Any]:
    row = db.execute(
        "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate #{candidate_id} not found",
        )
    return dict(row)


@router.get("/{candidate_id}", response_model=CandidateDetail)
async def get_candidate(
    candidate_id: int,
    db: DB,
    user: CurrentUser,
) -> CandidateDetail:
    """Full candidate detail with rule trace, veto trace, llm evaluation,
    selected contract, and lifecycle events. Returns a single
    `copyable_text` block ready to paste into Claude.ai."""
    row = _load_candidate_row(db, candidate_id)
    rule_trace = json.loads(row["rule_trace_json"]) if row.get("rule_trace_json") else None
    veto_trace_dict = fetch_latest_veto_trace(db, candidate_id)
    veto_trace = (
        json.loads(veto_trace_dict["trace_json"])
        if veto_trace_dict and veto_trace_dict.get("trace_json")
        else None
    )
    selected_contract = (
        json.loads(row["selected_contract_json"])
        if row.get("selected_contract_json")
        else None
    )
    eval_rows = fetch_recent_evaluations(db, candidate_id=candidate_id, hours=24 * 30)
    llm_evaluation = eval_rows[0] if eval_rows else None

    lifecycle: list[dict[str, Any]] = []
    if row.get("position_id"):
        events = await get_position_lifecycle(
            db, int(row["position_id"]), limit=50
        )
        lifecycle = [e.model_dump(mode="json") for e in events]

    parts = [
        f"# Candidate #{candidate_id} ({row['ticker']} {row['direction']})",
        f"status={row['status']}  kind={row['candidate_kind']}",
        "",
        "## Rule trace",
        json.dumps(rule_trace, indent=2, default=str) if rule_trace else "(none)",
        "",
        "## Veto trace",
        json.dumps(veto_trace, indent=2, default=str) if veto_trace else "(none)",
        "",
        "## Selected contract",
        json.dumps(selected_contract, indent=2, default=str) if selected_contract else "(none)",
        "",
        "## LLM evaluation",
        json.dumps(llm_evaluation, indent=2, default=str) if llm_evaluation else "(none)",
        "",
        "## Lifecycle events",
        json.dumps(lifecycle, indent=2, default=str) if lifecycle else "(none)",
    ]
    copyable = "\n".join(parts)

    return CandidateDetail(
        candidate=row,
        rule_trace=rule_trace,
        veto_trace=veto_trace,
        selected_contract=selected_contract,
        llm_evaluation=llm_evaluation,
        lifecycle_events=lifecycle,
        copyable_text=copyable,
    )


def _approvable_status() -> set[str]:
    return {"pending_human_approval"}


@router.post("/{candidate_id}/approve", response_model=CandidateActionResponse)
async def approve_candidate(
    candidate_id: int,
    payload: ApproveRequest,
    db: DB,
    user: CurrentUser,
) -> CandidateActionResponse:
    """Transition pending_human_approval → approved. Idempotent (already
    approved → 200). Returns 409 if not in approvable state."""
    row = _load_candidate_row(db, candidate_id)
    cur_status = row["status"]
    if cur_status == "approved":
        return CandidateActionResponse(
            id=candidate_id, new_status="approved", already_processed=True
        )
    if cur_status not in _approvable_status():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot approve from status '{cur_status}'",
        )
    overrides = json.loads(row["overrides_applied_json"] or "{}")
    if payload.notes:
        overrides["approval_notes"] = payload.notes
    if payload.quantity_override is not None:
        overrides["quantity_override"] = payload.quantity_override
    db.execute(
        "UPDATE candidates SET status = 'approved', updated_ts = ?, "
        "human_decision = 'approved', human_decision_ts = ?, "
        "overrides_applied_json = ? WHERE id = ?",
        (time.time(), time.time(), json.dumps(overrides, default=str), candidate_id),
    )
    db.commit()
    emit(
        "api",
        "info",
        "candidate_approved",
        {"candidate_id": candidate_id, "user_id": user.id},
    )
    return CandidateActionResponse(
        id=candidate_id, new_status="approved", already_processed=False
    )


@router.post("/{candidate_id}/reject", response_model=CandidateActionResponse)
async def reject_candidate(
    candidate_id: int,
    payload: RejectRequest,
    db: DB,
    user: CurrentUser,
) -> CandidateActionResponse:
    """Transition pending_human_approval → rejected_by_user."""
    row = _load_candidate_row(db, candidate_id)
    cur_status = row["status"]
    if cur_status == "rejected_by_user":
        return CandidateActionResponse(
            id=candidate_id,
            new_status="rejected_by_user",
            already_processed=True,
        )
    if cur_status not in _approvable_status():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot reject from status '{cur_status}'",
        )
    overrides = json.loads(row["overrides_applied_json"] or "{}")
    if payload.notes or payload.reason:
        overrides["rejection_notes"] = payload.notes
        overrides["rejection_reason"] = payload.reason
    db.execute(
        "UPDATE candidates SET status = 'rejected_by_user', updated_ts = ?, "
        "human_decision = 'rejected', human_decision_ts = ?, "
        "overrides_applied_json = ? WHERE id = ?",
        (time.time(), time.time(), json.dumps(overrides, default=str), candidate_id),
    )
    db.commit()
    emit(
        "api",
        "info",
        "candidate_rejected",
        {"candidate_id": candidate_id, "user_id": user.id, "reason": payload.reason},
    )
    return CandidateActionResponse(
        id=candidate_id,
        new_status="rejected_by_user",
        already_processed=False,
    )


# Avoid unused-import warning in some linters
_ = timedelta
