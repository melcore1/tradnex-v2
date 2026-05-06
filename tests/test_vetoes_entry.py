"""Entry veto tests V1-V10 + aggregate behavior."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from shared.clients.halt_feed import Halt
from shared.clients.mock_halt_feed import MockHaltFeed
from shared.services.calendar_service import CalendarService
from shared.strategy.vetoes.base import (
    OrchestratorCandidate,
    VetoContext,
    VetoSettings,
)
from shared.strategy.vetoes.entry import (
    v1_strategy_paused,
    v2_outside_market_window,
    v3_weekly_trade_cap,
    v4_weekly_loss_circuit_breaker,
    v5_concurrent_positions_cap,
    v6_earnings_blackout,
    v7_macro_event_window,
    v8_active_halt,
    v9_vix_spike,
    v10_duplicate_candidate,
)
from shared.strategy.vetoes.runner import run_vetoes

ET = ZoneInfo("America/New_York")


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ve.db"))
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
    """Return today's UTC time corresponding to the given ET hour/minute."""
    et_dt = datetime.now(ET).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return et_dt.astimezone(UTC)


def _candidate(*, ticker: str = "NVDA", direction: str = "long_call") -> OrchestratorCandidate:
    return OrchestratorCandidate(
        id=1,
        candidate_kind="entry",
        ticker=ticker,
        direction=direction,  # type: ignore[arg-type]
        status="pending",
        created_ts=datetime.now(UTC).timestamp(),
        position_id=None,
    )


def _ctx(conn, *, halt_feed=None, current_time=None, settings=None) -> VetoContext:
    return VetoContext(
        conn=conn,
        calendar_service=CalendarService(conn),
        halt_feed=halt_feed or MockHaltFeed(),
        settings=settings or VetoSettings(),
        current_time_utc=current_time or _utc_for_et(10, 0),  # 10:00 ET
    )


async def test_v1_fires_when_strategy_paused(db_conn) -> None:
    conn = db_conn
    conn.execute(
        "UPDATE strategy_configs SET settings_json = ? WHERE name = 'default'",
        (json.dumps({"paused": True}),),
    )
    conn.commit()
    result = await v1_strategy_paused(_candidate(), _ctx(conn))
    assert result.failed
    assert "paused" in result.failure_reason.lower()


async def test_v1_passes_when_not_paused(db_conn) -> None:
    result = await v1_strategy_paused(_candidate(), _ctx(db_conn))
    assert not result.failed


async def test_v2_fires_outside_window(db_conn) -> None:
    # 17:00 ET is past 15:00 cutoff
    result = await v2_outside_market_window(
        _candidate(), _ctx(db_conn, current_time=_utc_for_et(17, 0))
    )
    assert result.failed


async def test_v2_passes_inside_window(db_conn) -> None:
    result = await v2_outside_market_window(
        _candidate(), _ctx(db_conn, current_time=_utc_for_et(10, 30))
    )
    assert not result.failed


async def test_v3_fires_at_weekly_cap(db_conn) -> None:
    now = datetime.now(UTC)
    week_start = now - timedelta(days=now.weekday())
    # Insert 10 placed candidates this week
    for _ in range(10):
        db_conn.execute(
            "INSERT INTO candidates (ticker, direction, status, created_ts, "
            "updated_ts, candidate_kind) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "NVDA",
                "long_call",
                "placed",
                week_start.timestamp() + 100,
                week_start.timestamp() + 100,
                "entry",
            ),
        )
    db_conn.commit()
    result = await v3_weekly_trade_cap(_candidate(), _ctx(db_conn))
    assert result.failed
    assert result.details["count"] == 10


async def test_v4_fires_when_weekly_loss_below_threshold(db_conn) -> None:
    # Insert a closed position with -4000 pnl (below default -3% of 100k = -3000)
    now_ts = datetime.now(UTC).timestamp()
    db_conn.execute(
        "INSERT INTO positions (ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts, exit_price, exit_ts, pnl, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("NVDA", "X", "long", 1, 5.0, now_ts - 100000, 1.0, now_ts - 1000, -4000.0, "closed"),
    )
    db_conn.commit()
    result = await v4_weekly_loss_circuit_breaker(_candidate(), _ctx(db_conn))
    assert result.failed


async def test_v5_fires_at_concurrent_cap(db_conn) -> None:
    now_ts = datetime.now(UTC).timestamp()
    for _ in range(5):
        db_conn.execute(
            "INSERT INTO positions (ticker, contract_symbol, side, quantity, "
            "entry_price, entry_ts, status) VALUES ('NVDA', 'X', 'long', 1, 2.0, ?, 'open')",
            (now_ts,),
        )
    db_conn.commit()
    result = await v5_concurrent_positions_cap(_candidate(), _ctx(db_conn))
    assert result.failed
    assert result.details["open_count"] == 5


async def test_v6_fires_within_earnings_blackout(db_conn) -> None:
    # Inject NVDA earnings 3 days out
    from shared.clients.calendar_feed import CalendarEvent

    ev = CalendarEvent(
        event_type="earnings",
        ticker="NVDA",
        event_name="NVDA Earnings",
        event_datetime_utc=datetime.now(UTC) + timedelta(days=3),
        impact="high",
        source="test",
    )
    await CalendarService.upsert_event(db_conn, ev)
    result = await v6_earnings_blackout(_candidate(), _ctx(db_conn))
    assert result.failed


async def test_v6_passes_when_earnings_far_out(db_conn) -> None:
    from shared.clients.calendar_feed import CalendarEvent

    ev = CalendarEvent(
        event_type="earnings",
        ticker="NVDA",
        event_name="NVDA Earnings",
        event_datetime_utc=datetime.now(UTC) + timedelta(days=30),
        impact="high",
        source="test",
    )
    await CalendarService.upsert_event(db_conn, ev)
    result = await v6_earnings_blackout(_candidate(), _ctx(db_conn))
    assert not result.failed


async def test_v7_fires_on_high_impact_macro(db_conn) -> None:
    from shared.clients.calendar_feed import CalendarEvent

    ev = CalendarEvent(
        event_type="economic",
        ticker=None,
        event_name="FOMC",
        event_datetime_utc=datetime.now(UTC) + timedelta(hours=12),
        impact="high",
        source="test",
    )
    await CalendarService.upsert_event(db_conn, ev)
    result = await v7_macro_event_window(_candidate(), _ctx(db_conn))
    assert result.failed


async def test_v8_fires_when_halted(db_conn) -> None:
    halt_feed = MockHaltFeed()
    halt_feed.inject_halt(
        Halt(
            ticker="NVDA",
            halt_time=datetime.now(UTC),
            halt_reason="LUDP",
            halt_code="LUDP",
            is_active=True,
        )
    )
    result = await v8_active_halt(_candidate(), _ctx(db_conn, halt_feed=halt_feed))
    assert result.failed


async def test_v9_deferred_always_passes(db_conn) -> None:
    result = await v9_vix_spike(_candidate(), _ctx(db_conn))
    assert not result.failed
    assert result.details.get("deferred") is True


async def test_v10_fires_on_duplicate(db_conn) -> None:
    # Existing duplicate candidate within window — pin both the test-current
    # time and the inserted candidate's created_ts to the same anchor so
    # window math works regardless of wall-clock hour during test runs.
    fake_now = datetime.now(UTC)
    fake_ts = fake_now.timestamp()
    db_conn.execute(
        "INSERT INTO candidates (ticker, direction, status, created_ts, "
        "updated_ts, candidate_kind) VALUES ('NVDA', 'long_call', 'pending', ?, ?, 'entry')",
        (fake_ts - 600, fake_ts - 600),
    )
    db_conn.commit()
    cand = OrchestratorCandidate(
        id=999,
        candidate_kind="entry",
        ticker="NVDA",
        direction="long_call",
        status="pending",
        created_ts=fake_ts,
    )
    result = await v10_duplicate_candidate(cand, _ctx(db_conn, current_time=fake_now))
    assert result.failed


async def test_runner_traces_all_vetoes_even_when_one_fails(db_conn) -> None:
    halt_feed = MockHaltFeed()
    halt_feed.inject_halt(
        Halt(
            ticker="NVDA",
            halt_time=datetime.now(UTC),
            halt_reason="x",
            halt_code="x",
            is_active=True,
        )
    )
    trace = await run_vetoes(_candidate(), _ctx(db_conn, halt_feed=halt_feed))
    assert len(trace.results) == 10  # all 10 entry vetoes ran
    assert trace.any_failed
    assert "V8_active_halt" in trace.failed_veto_names


async def test_runner_handles_buggy_veto(db_conn) -> None:
    """A veto that raises shouldn't crash the runner."""
    from unittest.mock import patch

    async def bomb(*args, **kwargs):
        raise RuntimeError("intentional")

    bomb.__name__ = "v8_active_halt"
    with patch("shared.strategy.vetoes.runner.ENTRY_VETOES", [bomb]):
        trace = await run_vetoes(_candidate(), _ctx(db_conn))
    assert len(trace.results) == 1
    assert trace.results[0].failed is False
    assert "intentional" in trace.results[0].details.get("error", "")
