"""Backup poller tests."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from services.orchestrator.poller import poll_for_stragglers
from shared.clients.mock_halt_feed import MockHaltFeed
from shared.services.calendar_service import CalendarService
from shared.strategy.vetoes.base import VetoContext, VetoSettings

ET = ZoneInfo("America/New_York")


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "po.db"))
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


def _ctx(conn) -> VetoContext:
    return VetoContext(
        conn=conn,
        calendar_service=CalendarService(conn),
        halt_feed=MockHaltFeed(),
        settings=VetoSettings(),
        current_time_utc=_utc_for_et(10, 0),
    )


def _insert_pending(conn, *, age_seconds: float = 0) -> int:
    ts = datetime.now(UTC).timestamp() - age_seconds
    cur = conn.execute(
        "INSERT INTO candidates (ticker, direction, status, created_ts, updated_ts, "
        "candidate_kind, strategy_name) VALUES (?, ?, 'pending', ?, ?, 'entry', ?)",
        ("NVDA", "long_call", ts, ts, "long_options_momentum"),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


async def test_poller_processes_stale_pending(db_conn) -> None:
    cid = _insert_pending(db_conn, age_seconds=600)  # 10 min old
    count = await poll_for_stragglers(_ctx(db_conn), stale_seconds=300)
    assert count == 1
    row = db_conn.execute("SELECT status FROM candidates WHERE id = ?", (cid,)).fetchone()
    assert row["status"] in ("pending_llm_evaluation", "vetoed")


async def test_poller_skips_fresh_candidates(db_conn) -> None:
    _insert_pending(db_conn, age_seconds=60)  # 1 min old
    count = await poll_for_stragglers(_ctx(db_conn), stale_seconds=300)
    assert count == 0


async def test_poller_returns_count(db_conn) -> None:
    for _ in range(3):
        _insert_pending(db_conn, age_seconds=600)
    count = await poll_for_stragglers(_ctx(db_conn), stale_seconds=300)
    assert count == 3
