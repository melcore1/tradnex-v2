"""CalendarService read + upsert."""

from datetime import UTC, datetime, timedelta

import pytest

from shared.clients.calendar_feed import CalendarEvent
from shared.services.calendar_service import CalendarService


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "cs.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


def _ev(
    *,
    event_type: str = "economic",
    ticker: str | None = None,
    name: str = "Test Event",
    days: float = 1.0,
    impact: str = "medium",
) -> CalendarEvent:
    return CalendarEvent(
        event_type=event_type,  # type: ignore[arg-type]
        ticker=ticker,
        event_name=name,
        event_datetime_utc=datetime.now(UTC) + timedelta(days=days),
        impact=impact,  # type: ignore[arg-type]
        source="test",
    )


async def test_upsert_and_read_roundtrip(db_conn) -> None:
    ev = _ev(name="FOMC", days=2)
    inserted = await CalendarService.upsert_event(db_conn, ev)
    assert inserted == 1
    # Re-upsert is idempotent
    again = await CalendarService.upsert_event(db_conn, ev)
    assert again == 0
    svc = CalendarService(db_conn)
    rows = await svc.get_events_in_window(
        datetime.now(UTC), datetime.now(UTC) + timedelta(days=10)
    )
    assert len(rows) == 1
    assert rows[0].event_name == "FOMC"


async def test_in_window_filter(db_conn) -> None:
    near = _ev(name="Near", days=2)
    far = _ev(name="Far", days=20)
    await CalendarService.upsert_event(db_conn, near)
    await CalendarService.upsert_event(db_conn, far)
    svc = CalendarService(db_conn)
    rows = await svc.get_events_in_window(
        datetime.now(UTC), datetime.now(UTC) + timedelta(days=10)
    )
    assert {e.event_name for e in rows} == {"Near"}


async def test_impact_filter(db_conn) -> None:
    low = _ev(name="L", days=1, impact="low")
    high = _ev(name="H", days=2, impact="high")
    await CalendarService.upsert_event(db_conn, low)
    await CalendarService.upsert_event(db_conn, high)
    svc = CalendarService(db_conn)
    rows = await svc.get_events_in_window(
        datetime.now(UTC),
        datetime.now(UTC) + timedelta(days=5),
        impact_min="medium",
    )
    assert {e.event_name for e in rows} == {"H"}


async def test_ticker_filter(db_conn) -> None:
    nvda = _ev(name="NVDA Earnings", event_type="earnings", ticker="NVDA", days=5)
    amd = _ev(name="AMD Earnings", event_type="earnings", ticker="AMD", days=6)
    await CalendarService.upsert_event(db_conn, nvda)
    await CalendarService.upsert_event(db_conn, amd)
    svc = CalendarService(db_conn)
    rows = await svc.get_events_in_window(
        datetime.now(UTC),
        datetime.now(UTC) + timedelta(days=10),
        event_type="earnings",
        ticker="NVDA",
    )
    assert len(rows) == 1
    assert rows[0].ticker == "NVDA"


async def test_get_next_earnings_returns_first_future(db_conn) -> None:
    earlier = _ev(name="E1", event_type="earnings", ticker="NVDA", days=5)
    later = _ev(name="E2", event_type="earnings", ticker="NVDA", days=15)
    await CalendarService.upsert_event(db_conn, later)
    await CalendarService.upsert_event(db_conn, earlier)
    svc = CalendarService(db_conn)
    next_e = await svc.get_next_earnings("NVDA")
    assert next_e is not None
    assert next_e.event_name == "E1"


async def test_has_high_impact_within_hours(db_conn) -> None:
    soon_high = _ev(name="FOMC", days=0.5, impact="high")
    later_low = _ev(name="Random", days=2, impact="low")
    await CalendarService.upsert_event(db_conn, soon_high)
    await CalendarService.upsert_event(db_conn, later_low)
    svc = CalendarService(db_conn)
    assert await svc.has_high_impact_within(24, event_type="economic") is True
    # Window of 6h does NOT contain FOMC at +12h
    assert await svc.has_high_impact_within(6, event_type="economic") is False
    # Empty for ticker that doesn't exist
    assert (
        await svc.has_high_impact_within(48, event_type="earnings", ticker="NVDA")
        is False
    )
