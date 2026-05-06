"""DB persistence for candidates and scanner_evaluations rows."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from shared.analytics.full_analysis import FullAnalysis
from shared.analytics.options.full_options_analysis import FullOptionsAnalysis
from shared.analytics.regime import RegimeState
from shared.strategy.base import EntryCandidate, RuleTrace


async def persist_candidate(
    conn: sqlite3.Connection,
    candidate: EntryCandidate,
) -> int:
    """Insert a fired candidate. Returns the new row id."""
    now_ts = datetime.now().timestamp()
    shortlist_payload: str | None
    if candidate.shortlist is None:
        shortlist_payload = None
    else:
        shortlist_payload = json.dumps(
            [c.model_dump(mode="json") for c in candidate.shortlist]
        )
    options_payload: str | None
    if candidate.options_analysis is None:
        options_payload = None
    else:
        options_payload = candidate.options_analysis.model_dump_json()

    cur = conn.execute(
        "INSERT INTO candidates ("
        "ticker, direction, status, created_ts, updated_ts, "
        "indicators_json, veto_trace_json, llm_decision_json, "
        "candidate_kind, strategy_name, rule_trace_json, regime_snapshot_json, "
        "overrides_applied_json, shortlist_json, full_analysis_json, "
        "options_analysis_json, position_id"
        ") VALUES (?, ?, 'pending', ?, ?, '{}', '{}', '{}', "
        "?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (
            candidate.ticker,
            candidate.direction,
            now_ts,
            now_ts,
            candidate.candidate_kind,
            candidate.strategy_name,
            candidate.rule_trace.model_dump_json(),
            candidate.regime.model_dump_json(),
            json.dumps(candidate.overrides_applied, default=str),
            shortlist_payload,
            candidate.full_analysis.model_dump_json(),
            options_payload,
        ),
    )
    conn.commit()
    inserted_id = cur.lastrowid
    if inserted_id is None:
        raise RuntimeError("Failed to insert candidate row")
    return int(inserted_id)


async def persist_evaluation(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    cycle_id: str,
    rule_trace: RuleTrace,
    full_analysis: FullAnalysis,
    options_analysis: FullOptionsAnalysis | None,
    regime: RegimeState | None,
    candidate_id: int | None,
) -> int:
    """Insert one scanner_evaluations row. Returns the new row id."""
    now_ts = datetime.now().timestamp()
    fired = 1 if rule_trace.fired else 0
    full_summary = full_analysis.summary if full_analysis is not None else None
    options_summary = options_analysis.summary if options_analysis is not None else None
    regime_summary = regime.description if regime is not None else None

    cur = conn.execute(
        "INSERT INTO scanner_evaluations ("
        "ticker, strategy_name, fired, rule_trace_json, "
        "full_analysis_summary, options_analysis_summary, regime_summary, "
        "candidate_id, timestamp, cycle_id"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ticker.upper(),
            "long_options_momentum",
            fired,
            rule_trace.model_dump_json(),
            full_summary,
            options_summary,
            regime_summary,
            candidate_id,
            now_ts,
            cycle_id,
        ),
    )
    conn.commit()
    inserted_id = cur.lastrowid
    if inserted_id is None:
        raise RuntimeError("Failed to insert scanner_evaluations row")
    return int(inserted_id)


def fetch_recent_evaluations(
    conn: sqlite3.Connection,
    *,
    ticker: str | None = None,
    hours: int = 24,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Read scanner_evaluations within the last `hours`, optional ticker filter."""
    cutoff = datetime.now().timestamp() - (hours * 3600)
    sql = (
        "SELECT id, ticker, strategy_name, fired, rule_trace_json, "
        "full_analysis_summary, options_analysis_summary, regime_summary, "
        "candidate_id, timestamp, cycle_id FROM scanner_evaluations "
        "WHERE timestamp >= ?"
    )
    params: list[Any] = [cutoff]
    if ticker is not None:
        sql += " AND ticker = ?"
        params.append(ticker.upper())
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def fetch_candidate(
    conn: sqlite3.Connection,
    candidate_id: int,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, ticker, direction, status, candidate_kind, strategy_name, "
        "rule_trace_json, regime_snapshot_json, overrides_applied_json, "
        "shortlist_json, full_analysis_json, options_analysis_json, "
        "created_ts, updated_ts, position_id FROM candidates WHERE id = ?",
        (candidate_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def fetch_recent_candidates(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT id, ticker, direction, status, candidate_kind, strategy_name, "
        "created_ts FROM candidates"
    )
    params: list[Any] = []
    if status is not None:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_ts DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
