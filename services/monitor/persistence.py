"""DB persistence for monitor_evaluations + ExitCandidate (in candidates table)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from shared.strategy.base import ExitCandidate
from shared.strategy.exit_signals.base import ExitSignalTrace


async def persist_monitor_evaluation(
    conn: sqlite3.Connection,
    *,
    trace: ExitSignalTrace,
    cycle_id: str,
    halt_status_at_eval: str | None,
    underlying_summary: str | None,
    current_delta: float | None,
    current_iv: float | None,
    exit_candidate_id: int | None,
) -> int:
    """Insert one monitor_evaluations row."""
    now_ts = datetime.now().timestamp()
    fired_count = sum(1 for s in trace.signals if s.triggered)
    cur = conn.execute(
        "INSERT INTO monitor_evaluations ("
        "position_id, cycle_id, current_pnl_pct, current_pnl_dollars, "
        "current_delta, current_iv, dte_remaining, signal_trace_json, "
        "signals_fired_count, auto_close_triggered, exit_candidate_id, "
        "underlying_summary, halt_status_at_eval, timestamp"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            trace.position_id,
            cycle_id,
            float(trace.pnl_pct),
            float(trace.pnl_dollars),
            current_delta,
            current_iv,
            trace.dte_remaining,
            trace.model_dump_json(),
            fired_count,
            1 if trace.auto_close_triggered else 0,
            exit_candidate_id,
            underlying_summary,
            halt_status_at_eval,
            now_ts,
        ),
    )
    conn.commit()
    inserted_id = cur.lastrowid
    if inserted_id is None:
        raise RuntimeError("Failed to insert monitor_evaluations row")
    return int(inserted_id)


async def persist_exit_candidate(
    conn: sqlite3.Connection,
    candidate: ExitCandidate,
) -> int:
    """Insert an ExitCandidate row into the shared `candidates` table.

    Stores `signal_trace_json` (the full ExitSignalTrace), `position_id`
    (FK), and routing flags inside `overrides_applied_json` for visibility.
    `direction` is taken from the position so the existing CHECK passes —
    we look it up in the caller.
    """
    now_ts = datetime.now().timestamp()
    routing_payload: dict[str, Any] = {
        "is_auto_close": candidate.is_auto_close,
        "needs_claude": candidate.needs_claude,
        "auto_close_reason": candidate.auto_close_reason,
        "triggered_signals": list(candidate.triggered_signals),
    }
    cur = conn.execute(
        "INSERT INTO candidates ("
        "ticker, direction, status, created_ts, updated_ts, "
        "indicators_json, veto_trace_json, llm_decision_json, "
        "candidate_kind, strategy_name, rule_trace_json, regime_snapshot_json, "
        "overrides_applied_json, shortlist_json, full_analysis_json, "
        "options_analysis_json, position_id"
        ") VALUES (?, 'long_call', 'pending', ?, ?, '{}', '{}', '{}', "
        "?, ?, ?, NULL, ?, NULL, NULL, NULL, ?)",
        (
            candidate.ticker,
            now_ts,
            now_ts,
            candidate.candidate_kind,
            "long_options_momentum",
            candidate.signal_trace.model_dump_json(),
            json.dumps(routing_payload, default=str),
            candidate.position_id,
        ),
    )
    conn.commit()
    inserted_id = cur.lastrowid
    if inserted_id is None:
        raise RuntimeError("Failed to insert exit candidate row")
    return int(inserted_id)


def fetch_recent_monitor_evaluations(
    conn: sqlite3.Connection,
    *,
    position_id: int | None = None,
    hours: int = 24,
    limit: int = 200,
) -> list[dict[str, Any]]:
    cutoff = datetime.now().timestamp() - (hours * 3600)
    sql = (
        "SELECT id, position_id, cycle_id, current_pnl_pct, dte_remaining, "
        "signal_trace_json, signals_fired_count, auto_close_triggered, "
        "exit_candidate_id, underlying_summary, halt_status_at_eval, "
        "timestamp FROM monitor_evaluations WHERE timestamp >= ?"
    )
    params: list[Any] = [cutoff]
    if position_id is not None:
        sql += " AND position_id = ?"
        params.append(position_id)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def fetch_exit_candidates(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT id, ticker, direction, status, candidate_kind, strategy_name, "
        "position_id, overrides_applied_json, created_ts FROM candidates "
        "WHERE candidate_kind = 'exit'"
    )
    params: list[Any] = []
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY created_ts DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
