"""Orchestrator DB ops: load candidate metadata, persist veto traces,
update candidate status."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from shared.strategy.vetoes.base import OrchestratorCandidate, VetoTrace


class CandidateNotFoundError(LookupError):
    """Raised when load_candidate is given an id that doesn't exist."""


async def load_candidate(
    conn: sqlite3.Connection, candidate_id: int
) -> OrchestratorCandidate:
    row = conn.execute(
        "SELECT id, ticker, direction, status, candidate_kind, position_id, "
        "overrides_applied_json, created_ts FROM candidates WHERE id = ?",
        (candidate_id,),
    ).fetchone()
    if row is None:
        raise CandidateNotFoundError(f"Candidate #{candidate_id} not found")
    is_auto_close = False
    if row["overrides_applied_json"]:
        try:
            payload = json.loads(row["overrides_applied_json"])
            is_auto_close = bool(payload.get("is_auto_close", False))
        except (json.JSONDecodeError, AttributeError):
            is_auto_close = False
    return OrchestratorCandidate(
        id=int(row["id"]),
        candidate_kind=row["candidate_kind"],
        ticker=row["ticker"],
        direction=row["direction"],
        status=row["status"],
        created_ts=float(row["created_ts"]),
        position_id=row["position_id"],
        is_auto_close=is_auto_close,
    )


async def update_candidate_status(
    conn: sqlite3.Connection,
    candidate_id: int,
    new_status: str,
) -> None:
    conn.execute(
        "UPDATE candidates SET status = ?, updated_ts = ? WHERE id = ?",
        (new_status, datetime.now().timestamp(), candidate_id),
    )
    conn.commit()


async def persist_veto_trace(
    conn: sqlite3.Connection,
    trace: VetoTrace,
) -> int:
    cur = conn.execute(
        "INSERT INTO veto_traces "
        "(candidate_id, veto_set, trace_json, any_failed, "
        "failed_veto_names_json, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            trace.candidate_id,
            trace.veto_set,
            trace.model_dump_json(),
            1 if trace.any_failed else 0,
            json.dumps(trace.failed_veto_names),
            trace.timestamp.timestamp(),
        ),
    )
    conn.commit()
    inserted_id = cur.lastrowid
    if inserted_id is None:
        raise RuntimeError("Failed to insert veto_traces row")
    return int(inserted_id)


def fetch_latest_veto_trace(
    conn: sqlite3.Connection, candidate_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, candidate_id, veto_set, trace_json, any_failed, "
        "failed_veto_names_json, timestamp FROM veto_traces "
        "WHERE candidate_id = ? ORDER BY timestamp DESC LIMIT 1",
        (candidate_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def fetch_pending_candidate_ids(
    conn: sqlite3.Connection, *, stale_seconds: int = 300
) -> list[int]:
    cutoff = datetime.now().timestamp() - stale_seconds
    rows = conn.execute(
        "SELECT id FROM candidates WHERE status = 'pending' AND created_ts <= ?",
        (cutoff,),
    ).fetchall()
    return [int(r["id"]) for r in rows]
