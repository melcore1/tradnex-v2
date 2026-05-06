"""Orchestrator process_candidate tests."""

import json
from datetime import UTC, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from services.orchestrator.persistence import (
    CandidateNotFoundError,
    fetch_latest_veto_trace,
    load_candidate,
)
from services.orchestrator.process_candidate import process_candidate
from shared.clients.mock_halt_feed import MockHaltFeed
from shared.services.calendar_service import CalendarService
from shared.strategy.vetoes.base import (
    VetoContext,
    VetoSettings,
)

ET = ZoneInfo("America/New_York")


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "op.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


def _utc_for_et(hour: int, minute: int = 0) -> datetime:
    et_dt = datetime.now(ET).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return et_dt.astimezone(UTC)


def _ctx(conn, *, current_time=None, halt_feed=None) -> VetoContext:
    return VetoContext(
        conn=conn,
        calendar_service=CalendarService(conn),
        halt_feed=halt_feed or MockHaltFeed(),
        settings=VetoSettings(),
        current_time_utc=current_time or _utc_for_et(10, 0),
    )


def _insert_entry_candidate(conn, *, ticker: str = "NVDA") -> int:
    ts = datetime.now(UTC).timestamp()
    cur = conn.execute(
        "INSERT INTO candidates (ticker, direction, status, created_ts, updated_ts, "
        "candidate_kind, strategy_name) VALUES (?, ?, 'pending', ?, ?, 'entry', ?)",
        (ticker, "long_call", ts, ts, "long_options_momentum"),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def _insert_exit_candidate(conn, *, position_id: int, is_auto_close: bool) -> int:
    ts = datetime.now(UTC).timestamp()
    overrides = json.dumps(
        {
            "is_auto_close": is_auto_close,
            "needs_claude": not is_auto_close,
            "auto_close_reason": "test" if is_auto_close else None,
        }
    )
    cur = conn.execute(
        "INSERT INTO candidates (ticker, direction, status, created_ts, updated_ts, "
        "candidate_kind, strategy_name, position_id, overrides_applied_json) "
        "VALUES (?, ?, 'pending', ?, ?, 'exit', ?, ?, ?)",
        ("NVDA", "long_call", ts, ts, "long_options_momentum", position_id, overrides),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def _insert_position(conn, *, pid: int) -> None:
    import time

    conn.execute(
        "INSERT INTO positions (id, ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts, status) VALUES (?, 'NVDA', 'X', 'long', 1, 2.0, ?, 'open')",
        (pid, time.time()),
    )
    conn.commit()


async def test_entry_no_veto_transitions_to_pending_llm(db_conn) -> None:
    cid = _insert_entry_candidate(db_conn)
    result = await process_candidate(cid, _ctx(db_conn))
    assert result.new_status == "pending_llm_evaluation"
    row = db_conn.execute("SELECT status FROM candidates WHERE id = ?", (cid,)).fetchone()
    assert row["status"] == "pending_llm_evaluation"


async def test_entry_veto_fires_transitions_to_vetoed(db_conn) -> None:
    cid = _insert_entry_candidate(db_conn)
    # Outside market window forces V2 to fail
    result = await process_candidate(
        cid, _ctx(db_conn, current_time=_utc_for_et(17, 0))
    )
    assert result.new_status == "vetoed"
    failed = result.veto_trace.failed_veto_names if result.veto_trace else []
    assert "V2_outside_market_window" in failed


async def test_exit_auto_close_skips_llm(db_conn) -> None:
    _insert_position(db_conn, pid=1)
    cid = _insert_exit_candidate(db_conn, position_id=1, is_auto_close=True)
    result = await process_candidate(cid, _ctx(db_conn))
    assert result.new_status == "pending_human_approval"
    # Lifecycle event recorded
    rows = db_conn.execute(
        "SELECT event_type, payload_json FROM position_lifecycle_events WHERE position_id = 1"
    ).fetchall()
    assert any(r["event_type"] == "monitor_evaluated" for r in rows)


async def test_exit_non_auto_close_routes_to_llm(db_conn) -> None:
    _insert_position(db_conn, pid=1)
    cid = _insert_exit_candidate(db_conn, position_id=1, is_auto_close=False)
    result = await process_candidate(cid, _ctx(db_conn))
    assert result.new_status == "pending_llm_evaluation"


async def test_idempotent_on_reprocess(db_conn) -> None:
    cid = _insert_entry_candidate(db_conn)
    first = await process_candidate(cid, _ctx(db_conn))
    second = await process_candidate(cid, _ctx(db_conn))
    assert first.already_processed is False
    assert second.already_processed is True
    assert second.new_status == first.new_status


async def test_veto_trace_persisted(db_conn) -> None:
    cid = _insert_entry_candidate(db_conn)
    await process_candidate(cid, _ctx(db_conn))
    trace = fetch_latest_veto_trace(db_conn, cid)
    assert trace is not None
    assert trace["veto_set"] == "entry"
    parsed = json.loads(trace["trace_json"])
    assert len(parsed["results"]) == 10  # all 10 entry vetoes


async def test_buggy_veto_does_not_fail_process(db_conn) -> None:
    """A veto raising shouldn't crash process_candidate."""
    cid = _insert_entry_candidate(db_conn)

    async def bomb(*args, **kwargs):
        raise RuntimeError("boom")

    bomb.__name__ = "v8_active_halt"
    with patch("shared.strategy.vetoes.runner.ENTRY_VETOES", [bomb]):
        result = await process_candidate(cid, _ctx(db_conn))
    # Buggy veto returns failed=False, so no veto fires; transitions to pending_llm
    assert result.new_status == "pending_llm_evaluation"


async def test_sequential_candidates_traced(db_conn) -> None:
    cid1 = _insert_entry_candidate(db_conn, ticker="NVDA")
    cid2 = _insert_entry_candidate(db_conn, ticker="AMD")
    await process_candidate(cid1, _ctx(db_conn))
    await process_candidate(cid2, _ctx(db_conn))
    traces = db_conn.execute("SELECT COUNT(*) FROM veto_traces").fetchone()[0]
    assert traces == 2


async def test_nonexistent_id_raises_clear_error(db_conn) -> None:
    with pytest.raises(CandidateNotFoundError):
        await process_candidate(99999, _ctx(db_conn))


async def test_load_candidate_recognizes_auto_close(db_conn) -> None:
    _insert_position(db_conn, pid=1)
    cid = _insert_exit_candidate(db_conn, position_id=1, is_auto_close=True)
    cand = await load_candidate(db_conn, cid)
    assert cand.is_auto_close is True
    assert cand.candidate_kind == "exit"
    assert cand.position_id == 1
