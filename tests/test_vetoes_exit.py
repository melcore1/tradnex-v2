"""Exit veto tests V_E1, V_E2."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from shared.clients.mock_halt_feed import MockHaltFeed
from shared.services.calendar_service import CalendarService
from shared.strategy.vetoes.base import (
    OrchestratorCandidate,
    VetoContext,
    VetoSettings,
)
from shared.strategy.vetoes.exit import (
    v_e1_outside_close_window,
    v_e2_duplicate_exit,
)

ET = ZoneInfo("America/New_York")


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "vex.db"))
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


def _candidate(*, position_id: int = 1) -> OrchestratorCandidate:
    return OrchestratorCandidate(
        id=42,
        candidate_kind="exit",
        ticker="NVDA",
        direction="long_call",
        status="pending",
        created_ts=datetime.now(UTC).timestamp(),
        position_id=position_id,
    )


def _ctx(conn, *, current_time) -> VetoContext:
    return VetoContext(
        conn=conn,
        calendar_service=CalendarService(conn),
        halt_feed=MockHaltFeed(),
        settings=VetoSettings(),
        current_time_utc=current_time,
    )


async def test_v_e1_fires_after_cutoff(db_conn) -> None:
    # 16:30 ET is past 15:55
    result = await v_e1_outside_close_window(
        _candidate(), _ctx(db_conn, current_time=_utc_for_et(16, 30))
    )
    assert result.failed


async def test_v_e1_passes_during_hours(db_conn) -> None:
    result = await v_e1_outside_close_window(
        _candidate(), _ctx(db_conn, current_time=_utc_for_et(10, 0))
    )
    assert not result.failed


def _insert_position(conn, *, pid: int) -> None:
    """Insert a placeholder open position so the FK constraint passes."""
    import time

    conn.execute(
        "INSERT INTO positions (id, ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (pid, "NVDA", "X", "long", 1, 2.0, time.time(), "open"),
    )
    conn.commit()


async def test_v_e2_fires_for_duplicate(db_conn) -> None:
    _insert_position(db_conn, pid=1)
    now_ts = datetime.now(UTC).timestamp()
    db_conn.execute(
        "INSERT INTO candidates (ticker, direction, status, created_ts, "
        "updated_ts, candidate_kind, position_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("NVDA", "long_call", "pending", now_ts - 60, now_ts - 60, "exit", 1),
    )
    db_conn.commit()
    cand_with_id = _candidate(position_id=1).model_copy(update={"id": 999})
    result = await v_e2_duplicate_exit(
        cand_with_id, _ctx(db_conn, current_time=datetime.now(UTC))
    )
    assert result.failed


async def test_v_e2_passes_for_distinct_position(db_conn) -> None:
    _insert_position(db_conn, pid=99)
    now_ts = datetime.now(UTC).timestamp()
    db_conn.execute(
        "INSERT INTO candidates (ticker, direction, status, created_ts, "
        "updated_ts, candidate_kind, position_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("NVDA", "long_call", "pending", now_ts - 60, now_ts - 60, "exit", 99),
    )
    db_conn.commit()
    result = await v_e2_duplicate_exit(
        _candidate(position_id=1), _ctx(db_conn, current_time=datetime.now(UTC))
    )
    assert not result.failed
