"""/api/evaluations — read scanner, monitor, and LLM evaluation rows."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query

from services.api.deps import DB, CurrentUser
from services.evaluator.persistence import fetch_recent_evaluations as fetch_llm_evals
from services.monitor.persistence import fetch_recent_monitor_evaluations
from services.scanner.persistence import fetch_recent_evaluations as fetch_scanner_evals

router = APIRouter()


@router.get("/scanner")
async def list_scanner_evaluations(
    db: DB,
    user: CurrentUser,
    ticker: str | None = None,
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    """scanner_evaluations rows, newest first."""
    return fetch_scanner_evals(db, ticker=ticker, hours=hours, limit=limit)


@router.get("/monitor")
async def list_monitor_evaluations(
    db: DB,
    user: CurrentUser,
    position_id: int | None = None,
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    """monitor_evaluations rows, newest first."""
    return fetch_recent_monitor_evaluations(
        db, position_id=position_id, hours=hours, limit=limit
    )


@router.get("/llm")
async def list_llm_evaluations(
    db: DB,
    user: CurrentUser,
    candidate_id: int | None = None,
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(100, ge=1, le=500),
    fallback_only: bool = False,
    decision: Literal[
        "STRONG", "MODERATE", "WEAK", "VETO", "CLOSE", "CLOSE_PARTIAL", "HOLD"
    ]
    | None = None,
) -> list[dict[str, Any]]:
    """llm_evaluations rows, newest first."""
    rows = fetch_llm_evals(
        db, candidate_id=candidate_id, hours=hours, limit=limit
    )
    if fallback_only:
        rows = [r for r in rows if r.get("fallback_used")]
    if decision is not None:
        rows = [r for r in rows if r.get("decision") == decision]
    return rows
