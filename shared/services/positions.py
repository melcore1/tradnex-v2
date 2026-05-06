"""Position CRUD + lifecycle helpers + high-water-mark.

Used by the monitor service. Lifecycle events are append-only — never
deleted, never updated. positions.status stays simple ('open' | 'closed');
intermediate state lives in position_lifecycle_events.event_type.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from shared.events import emit
from shared.schemas.core import Position

LifecycleEventType = Literal[
    "opened",
    "monitor_evaluated",
    "signal_fired",
    "auto_close_triggered",
    "exit_candidate_created",
    "claude_evaluated",
    "human_approved",
    "human_rejected",
    "closing",
    "closed",
    "close_failed",
]

SERVICE_NAME = "monitor"


class LifecycleEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    position_id: int
    event_type: str
    cycle_id: str | None
    payload: dict[str, Any]
    timestamp: float


def _row_to_position(row: sqlite3.Row) -> Position:
    return Position(
        id=row["id"],
        candidate_id=row["candidate_id"],
        ticker=row["ticker"],
        contract_symbol=row["contract_symbol"],
        side=row["side"],
        quantity=int(row["quantity"]),
        entry_price=Decimal(str(row["entry_price"])),
        entry_ts=float(row["entry_ts"]),
        exit_price=Decimal(str(row["exit_price"])) if row["exit_price"] is not None else None,
        exit_ts=float(row["exit_ts"]) if row["exit_ts"] is not None else None,
        exit_reason=row["exit_reason"],
        pnl=Decimal(str(row["pnl"])) if row["pnl"] is not None else None,
        status=row["status"],
        entry_candidate_id=row["entry_candidate_id"],
        exit_candidate_id=row["exit_candidate_id"],
        strategy_name=(
            row["strategy_name"]
            if row["strategy_name"] is not None
            else "long_options_momentum"
        ),
        entry_iv=Decimal(str(row["entry_iv"])) if row["entry_iv"] is not None else None,
        entry_delta=Decimal(str(row["entry_delta"])) if row["entry_delta"] is not None else None,
        entry_dte=int(row["entry_dte"]) if row["entry_dte"] is not None else None,
    )


_POSITION_COLS = (
    "id, candidate_id, ticker, contract_symbol, side, quantity, "
    "entry_price, entry_ts, exit_price, exit_ts, exit_reason, pnl, status, "
    "entry_candidate_id, exit_candidate_id, strategy_name, "
    "entry_iv, entry_delta, entry_dte"
)


async def get_open_positions(conn: sqlite3.Connection) -> list[Position]:
    rows = conn.execute(
        f"SELECT {_POSITION_COLS} FROM positions WHERE status = 'open' ORDER BY id"
    ).fetchall()
    return [_row_to_position(r) for r in rows]


async def get_position(conn: sqlite3.Connection, position_id: int) -> Position | None:
    row = conn.execute(
        f"SELECT {_POSITION_COLS} FROM positions WHERE id = ?",
        (position_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_position(row)


async def update_position_status(
    conn: sqlite3.Connection,
    position_id: int,
    new_status: Literal["open", "closed"],
) -> None:
    """Update positions.status. Idempotent: re-applying the same status is a no-op.
    Only 'open' or 'closed' are valid here — intermediate states live in lifecycle events."""
    conn.execute(
        "UPDATE positions SET status = ? WHERE id = ?",
        (new_status, position_id),
    )
    conn.commit()


async def emit_lifecycle_event(
    conn: sqlite3.Connection,
    position_id: int,
    event_type: LifecycleEventType,
    *,
    cycle_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    """Append a lifecycle event. Returns the new row id."""
    now_ts = datetime.now().timestamp()
    payload_json = json.dumps(payload or {}, default=str)
    cur = conn.execute(
        "INSERT INTO position_lifecycle_events "
        "(position_id, event_type, cycle_id, payload_json, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (position_id, event_type, cycle_id, payload_json, now_ts),
    )
    conn.commit()
    new_id = cur.lastrowid
    if new_id is None:
        raise RuntimeError("Failed to insert position_lifecycle_events row")
    emit(
        SERVICE_NAME,
        "info",
        "lifecycle_event",
        {
            "position_id": position_id,
            "event_type": event_type,
            "cycle_id": cycle_id,
        },
    )
    return int(new_id)


async def get_position_lifecycle(
    conn: sqlite3.Connection,
    position_id: int,
    *,
    limit: int = 200,
) -> list[LifecycleEvent]:
    rows = conn.execute(
        "SELECT id, position_id, event_type, cycle_id, payload_json, timestamp "
        "FROM position_lifecycle_events "
        "WHERE position_id = ? "
        "ORDER BY timestamp DESC LIMIT ?",
        (position_id, limit),
    ).fetchall()
    out: list[LifecycleEvent] = []
    for r in rows:
        out.append(
            LifecycleEvent(
                id=r["id"],
                position_id=r["position_id"],
                event_type=r["event_type"],
                cycle_id=r["cycle_id"],
                payload=json.loads(r["payload_json"] or "{}"),
                timestamp=float(r["timestamp"]),
            )
        )
    return out


async def get_position_high_water_mark(
    conn: sqlite3.Connection,
    position_id: int,
) -> Decimal | None:
    """Max current_pnl_pct ever recorded in monitor_evaluations for this
    position. Returns None when no prior evaluations exist."""
    row = conn.execute(
        "SELECT MAX(current_pnl_pct) FROM monitor_evaluations WHERE position_id = ?",
        (position_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return Decimal(str(row[0]))
