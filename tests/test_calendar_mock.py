"""Mock calendar client tests."""

from datetime import UTC, date, datetime, timedelta

import pytest

from shared.clients.calendar_feed import CalendarEvent
from shared.clients.mock_calendar import MockCalendarClient


def test_inject_event_roundtrip() -> None:
    client = MockCalendarClient(auto_seed=False)
    event = CalendarEvent(
        event_type="economic",
        ticker=None,
        event_name="Test FOMC",
        event_datetime_utc=datetime.now(UTC) + timedelta(days=3),
        impact="high",
        source="test",
    )
    client.inject_event(event)
    today = date.today()
    end = today + timedelta(days=10)

    import asyncio

    out = asyncio.run(client.fetch_economic_calendar(today, end))
    assert len(out) == 1
    assert out[0].event_name == "Test FOMC"


def test_clear_events_resets() -> None:
    client = MockCalendarClient(auto_seed=False)
    client.inject_event(
        CalendarEvent(
            event_type="economic",
            event_name="X",
            event_datetime_utc=datetime.now(UTC) + timedelta(days=1),
            impact="high",
        )
    )
    client.clear_events()
    import asyncio

    out = asyncio.run(
        client.fetch_economic_calendar(date.today(), date.today() + timedelta(days=2))
    )
    assert out == []


@pytest.mark.asyncio
async def test_auto_seed_includes_fomc_cpi_and_earnings() -> None:
    client = MockCalendarClient()
    today = date.today()
    end = today + timedelta(days=90)
    economic = await client.fetch_economic_calendar(today, end)
    earnings = await client.fetch_earnings_calendar(today, end)
    names = {e.event_name for e in economic}
    assert "FOMC Rate Decision" in names
    assert "US CPI Release" in names
    assert any("NVDA" in e.event_name for e in earnings)
    # Universe filter
    nvda_only = await client.fetch_earnings_calendar(today, end, tickers=["NVDA"])
    assert all(e.ticker == "NVDA" for e in nvda_only)
