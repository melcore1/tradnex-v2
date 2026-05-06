"""Position lifecycle events: append-only audit + HWM."""

from decimal import Decimal

import pytest

from shared.services.positions import (
    emit_lifecycle_event,
    get_position_high_water_mark,
    get_position_lifecycle,
)


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "lc.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


def _insert_position(conn) -> int:
    import time

    cur = conn.execute(
        "INSERT INTO positions (ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts, status) VALUES ('NVDA', 'X', 'long', 1, 2.50, ?, 'open')",
        (time.time(),),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


async def test_emit_lifecycle_event_appends(db_conn) -> None:
    pid = _insert_position(db_conn)
    eid = await emit_lifecycle_event(
        db_conn, pid, "opened", payload={"price": "2.5"}
    )
    assert eid > 0
    row = db_conn.execute(
        "SELECT position_id, event_type, payload_json FROM position_lifecycle_events "
        "WHERE id = ?",
        (eid,),
    ).fetchone()
    assert row["position_id"] == pid
    assert row["event_type"] == "opened"
    import json

    assert json.loads(row["payload_json"]) == {"price": "2.5"}


async def test_get_position_lifecycle_orders_desc(db_conn) -> None:
    pid = _insert_position(db_conn)
    await emit_lifecycle_event(db_conn, pid, "opened")
    await emit_lifecycle_event(db_conn, pid, "monitor_evaluated", cycle_id="c1")
    await emit_lifecycle_event(db_conn, pid, "exit_candidate_created")
    events = await get_position_lifecycle(db_conn, pid)
    assert len(events) == 3
    types = [e.event_type for e in events]
    # Newest first
    assert types[0] == "exit_candidate_created"


async def test_event_types_constrained_by_check(db_conn) -> None:
    """SQLite CHECK constraint rejects bogus event_types."""
    import sqlite3

    pid = _insert_position(db_conn)
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO position_lifecycle_events "
            "(position_id, event_type, payload_json, timestamp) "
            "VALUES (?, 'bogus_event', '{}', 0)",
            (pid,),
        )
        db_conn.commit()


async def test_lifecycle_cascades_on_position_delete(db_conn) -> None:
    pid = _insert_position(db_conn)
    await emit_lifecycle_event(db_conn, pid, "opened")
    db_conn.execute("DELETE FROM positions WHERE id = ?", (pid,))
    db_conn.commit()
    rows = db_conn.execute(
        "SELECT COUNT(*) FROM position_lifecycle_events WHERE position_id = ?",
        (pid,),
    ).fetchone()
    assert rows[0] == 0


async def test_high_water_mark_returns_none_when_no_evaluations(db_conn) -> None:
    pid = _insert_position(db_conn)
    hwm = await get_position_high_water_mark(db_conn, pid)
    assert hwm is None


async def test_high_water_mark_returns_max_pnl(db_conn) -> None:
    import time

    pid = _insert_position(db_conn)
    # Insert a few monitor_evaluations rows with varying pnl_pct
    for pnl in (10.0, 35.0, 22.0):
        db_conn.execute(
            "INSERT INTO monitor_evaluations (position_id, cycle_id, current_pnl_pct, "
            "signal_trace_json, signals_fired_count, timestamp) "
            "VALUES (?, 'c', ?, '{}', 0, ?)",
            (pid, pnl, time.time()),
        )
    db_conn.commit()
    hwm = await get_position_high_water_mark(db_conn, pid)
    assert hwm == Decimal("35.0")
