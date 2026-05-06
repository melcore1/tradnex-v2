"""/api/dashboard — aggregating endpoints for hot-path UI screens."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query

from services.api.deps import DB, CurrentUser
from services.api.routers.system import status_ as system_status_handler
from services.api.routers.watchlist import _entry_to_response
from services.api.schemas import (
    ActiveTrade,
    DashboardSummary,
    JournalEntry,
    MorningView,
    PositionSummary,
)
from shared.services.calendar_service import CalendarService
from shared.services.positions import get_open_positions
from shared.services.universe import get_universe
from shared.services.watchlist import get_active_watchlist

router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
async def summary(db: DB, user: CurrentUser) -> DashboardSummary:
    """Homepage state in a single round trip."""
    watchlist_entry = await get_active_watchlist(db)
    open_pos = await get_open_positions(db)
    total_pnl: Decimal | None = None
    if open_pos:
        s = sum((p.pnl or Decimal("0")) for p in open_pos)
        total_pnl = Decimal(str(s)) if s != Decimal("0") else None
    pending_human = int(
        db.execute(
            "SELECT COUNT(*) FROM candidates "
            "WHERE status = 'pending_human_approval'"
        ).fetchone()[0]
    )
    pending_llm = int(
        db.execute(
            "SELECT COUNT(*) FROM candidates "
            "WHERE status = 'pending_llm_evaluation'"
        ).fetchone()[0]
    )
    rows = db.execute(
        "SELECT id, service, level, event_type, payload, timestamp "
        "FROM events ORDER BY timestamp DESC LIMIT 5"
    ).fetchall()
    recent: list[dict[str, Any]] = [dict(r) for r in rows]

    sys_status = await system_status_handler(db=db, user=user)

    return DashboardSummary(
        today_watchlist=_entry_to_response(watchlist_entry)
        if watchlist_entry.tickers
        else _entry_to_response(watchlist_entry),
        open_positions_count=len(open_pos),
        open_positions_total_pnl=total_pnl,
        pending_human_approvals=pending_human,
        pending_llm_evaluations=pending_llm,
        recent_events=recent,
        system_status=sys_status,
    )


@router.get("/morning-view", response_model=MorningView)
async def morning_view(db: DB, user: CurrentUser) -> MorningView:
    """8 AM ET planning view."""
    yday_start = (datetime.now(UTC) - timedelta(days=1)).timestamp()
    fired = int(
        db.execute(
            "SELECT COUNT(*) FROM candidates WHERE created_ts >= ?",
            (yday_start,),
        ).fetchone()[0]
    )
    approved = int(
        db.execute(
            "SELECT COUNT(*) FROM candidates "
            "WHERE created_ts >= ? AND status IN ('approved', 'placed')",
            (yday_start,),
        ).fetchone()[0]
    )
    rejected = int(
        db.execute(
            "SELECT COUNT(*) FROM candidates "
            "WHERE created_ts >= ? AND status IN "
            "('rejected_by_user', 'rejected_by_llm', 'vetoed')",
            (yday_start,),
        ).fetchone()[0]
    )
    yesterday_results: dict[str, Any] = {
        "fired": fired,
        "approved": approved,
        "rejected": rejected,
    }

    watchlist_entry = await get_active_watchlist(db)
    universe = await get_universe(db)

    svc = CalendarService(db)
    now = datetime.now(UTC)
    end = now + timedelta(days=7)
    events = await svc.get_events_in_window(now, end)
    upcoming_calendar = [e.model_dump(mode="json") for e in events]

    return MorningView(
        yesterday_results=yesterday_results,
        today_watchlist=_entry_to_response(watchlist_entry),
        universe=universe,
        upcoming_calendar=upcoming_calendar,
        pre_market_gaps=[],
    )


@router.get("/active-trades", response_model=list[ActiveTrade])
async def active_trades(db: DB, user: CurrentUser) -> list[ActiveTrade]:
    """All open positions with last monitor evaluation + any pending exit
    candidate. Built for the active-trades screen."""
    out: list[ActiveTrade] = []
    open_pos = await get_open_positions(db)
    for p in open_pos:
        latest = db.execute(
            "SELECT id, position_id, current_pnl_pct, dte_remaining, "
            "signal_trace_json, signals_fired_count, auto_close_triggered, "
            "exit_candidate_id, timestamp FROM monitor_evaluations "
            "WHERE position_id = ? ORDER BY timestamp DESC LIMIT 1",
            (p.id,),
        ).fetchone()
        pending_exit = db.execute(
            "SELECT id FROM candidates WHERE candidate_kind = 'exit' "
            "AND position_id = ? AND status IN "
            "('pending', 'pending_human_approval', 'pending_llm_evaluation', "
            "'processing_vetoes', 'processing_llm_evaluation') "
            "ORDER BY created_ts DESC LIMIT 1",
            (p.id,),
        ).fetchone()
        out.append(
            ActiveTrade(
                position=PositionSummary(
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
                ),
                latest_monitor_evaluation=dict(latest) if latest else None,
                pending_exit_candidate_id=int(pending_exit["id"])
                if pending_exit
                else None,
            )
        )
    return out


@router.get("/journal", response_model=JournalEntry)
async def journal(
    db: DB,
    user: CurrentUser,
    target_date: str | None = Query(None, alias="date"),
) -> JournalEntry:
    """End-of-day journal for a given date (default: today)."""
    if target_date is None:
        target_date = date.today().isoformat()
    start_ts = datetime.fromisoformat(target_date).replace(tzinfo=UTC).timestamp()
    end_ts = start_ts + 24 * 3600

    cycles = int(
        db.execute(
            "SELECT COUNT(DISTINCT cycle_id) FROM scanner_evaluations "
            "WHERE timestamp >= ? AND timestamp < ?",
            (start_ts, end_ts),
        ).fetchone()[0]
    )
    fired = int(
        db.execute(
            "SELECT COUNT(*) FROM candidates "
            "WHERE created_ts >= ? AND created_ts < ?",
            (start_ts, end_ts),
        ).fetchone()[0]
    )
    by_status_rows = db.execute(
        "SELECT status, COUNT(*) AS c FROM candidates "
        "WHERE created_ts >= ? AND created_ts < ? GROUP BY status",
        (start_ts, end_ts),
    ).fetchall()
    decisions = {r["status"]: int(r["c"]) for r in by_status_rows}

    state_changes_rows = db.execute(
        "SELECT id, position_id, event_type, cycle_id, payload_json, timestamp "
        "FROM position_lifecycle_events "
        "WHERE timestamp >= ? AND timestamp < ? "
        "ORDER BY timestamp ASC",
        (start_ts, end_ts),
    ).fetchall()
    state_changes = [
        {
            "id": int(r["id"]),
            "position_id": int(r["position_id"]),
            "event_type": r["event_type"],
            "cycle_id": r["cycle_id"],
            "payload": json.loads(r["payload_json"] or "{}"),
            "timestamp": float(r["timestamp"]),
        }
        for r in state_changes_rows
    ]

    pnl_row = db.execute(
        "SELECT SUM(pnl) AS total FROM positions "
        "WHERE status = 'closed' AND exit_ts >= ? AND exit_ts < ?",
        (start_ts, end_ts),
    ).fetchone()
    pnl_total = (
        Decimal(str(pnl_row["total"])) if pnl_row and pnl_row["total"] is not None else None
    )

    return JournalEntry(
        date=target_date,
        scanner_cycles_run=cycles,
        candidates_fired=fired,
        decisions=decisions,
        position_state_changes=state_changes,
        pnl_dollars=pnl_total,
    )
