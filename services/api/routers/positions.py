"""/api/positions — list, get, lifecycle."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status

from services.api.deps import DB, CurrentUser
from services.api.schemas import PositionDetail, PositionSummary
from services.monitor.persistence import fetch_recent_monitor_evaluations
from shared.services.positions import (
    get_open_positions,
    get_position,
    get_position_lifecycle,
)

router = APIRouter()


def _row_to_summary(p: Any) -> PositionSummary:
    return PositionSummary(
        id=int(p.id) if p.id is not None else 0,
        ticker=p.ticker,
        contract_symbol=p.contract_symbol,
        side=p.side,
        quantity=int(p.quantity),
        entry_price=p.entry_price,
        entry_ts=datetime.fromtimestamp(float(p.entry_ts), tz=UTC),
        status=p.status,
        pnl=p.pnl,
        pnl_pct=None,
    )


@router.get("", response_model=list[PositionSummary])
async def list_positions(
    db: DB,
    user: CurrentUser,
    position_status: Literal["open", "closed", "all"] = Query(
        "open", alias="status"
    ),
    limit: int = Query(100, ge=1, le=500),
) -> list[PositionSummary]:
    """List positions filtered by status."""
    if position_status == "open":
        positions = await get_open_positions(db)
        return [_row_to_summary(p) for p in positions[:limit]]
    sql = (
        "SELECT id, candidate_id, ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts, exit_price, exit_ts, exit_reason, pnl, status, "
        "entry_candidate_id, exit_candidate_id, strategy_name, "
        "entry_iv, entry_delta, entry_dte FROM positions"
    )
    params: list[Any] = []
    if position_status == "closed":
        sql += " WHERE status = 'closed'"
    sql += " ORDER BY entry_ts DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(sql, params).fetchall()
    out: list[PositionSummary] = []
    for r in rows:
        out.append(
            PositionSummary(
                id=int(r["id"]),
                ticker=r["ticker"],
                contract_symbol=r["contract_symbol"],
                side=r["side"],
                quantity=int(r["quantity"]),
                entry_price=Decimal(str(r["entry_price"])),
                entry_ts=datetime.fromtimestamp(float(r["entry_ts"]), tz=UTC),
                status=r["status"],
                pnl=(
                    Decimal(str(r["pnl"])) if r["pnl"] is not None else None
                ),
                pnl_pct=None,
            )
        )
    return out


@router.get("/{position_id}", response_model=PositionDetail)
async def get_position_detail(
    position_id: int,
    db: DB,
    user: CurrentUser,
) -> PositionDetail:
    """Full position detail with lifecycle events + latest monitor evaluation
    + any pending exit candidate."""
    p = await get_position(db, position_id)
    if p is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Position #{position_id} not found",
        )
    events = await get_position_lifecycle(db, position_id, limit=200)
    monitor_rows = fetch_recent_monitor_evaluations(
        db, position_id=position_id, hours=24, limit=1
    )
    pending_exit = db.execute(
        "SELECT id, status, created_ts FROM candidates "
        "WHERE candidate_kind = 'exit' AND position_id = ? "
        "AND status IN ('pending', 'pending_human_approval', "
        "'pending_llm_evaluation', 'processing_vetoes', 'processing_llm_evaluation') "
        "ORDER BY created_ts DESC LIMIT 1",
        (position_id,),
    ).fetchone()
    return PositionDetail(
        position=p.model_dump(mode="json"),
        lifecycle_events=[e.model_dump(mode="json") for e in events],
        latest_monitor_evaluation=monitor_rows[0] if monitor_rows else None,
        pending_exit_candidate=dict(pending_exit) if pending_exit else None,
    )


@router.get("/{position_id}/lifecycle")
async def list_position_lifecycle(
    position_id: int,
    db: DB,
    user: CurrentUser,
    limit: int = Query(200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Lifecycle events for a position, newest first."""
    if (await get_position(db, position_id)) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Position #{position_id} not found",
        )
    events = await get_position_lifecycle(db, position_id, limit=limit)
    return [e.model_dump(mode="json") for e in events]


# Suppress unused-import noise
_ = json
