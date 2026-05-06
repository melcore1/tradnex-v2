"""Nightly task: pull next 14 days of events from the calendar feed and
upsert into calendar_cache."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from shared.clients.calendar_feed import CalendarFeed
from shared.events import emit
from shared.services.calendar_service import CalendarService

SERVICE_NAME = "calendar"


async def refresh_calendar_cache(
    calendar_client: CalendarFeed,
    conn: sqlite3.Connection,
    universe: list[str],
    *,
    horizon_days: int = 14,
) -> tuple[int, int]:
    """Returns (economic_inserted, earnings_inserted)."""
    today = date.today()
    end = today + timedelta(days=horizon_days)

    economic = await calendar_client.fetch_economic_calendar(today, end)
    earnings = await calendar_client.fetch_earnings_calendar(today, end, tickers=universe)

    inserted_econ = 0
    for ev in economic:
        inserted_econ += await CalendarService.upsert_event(conn, ev)
    inserted_earn = 0
    for ev in earnings:
        inserted_earn += await CalendarService.upsert_event(conn, ev)

    emit(
        SERVICE_NAME,
        "info",
        "calendar_refreshed",
        {
            "economic_count": len(economic),
            "earnings_count": len(earnings),
            "economic_new_rows": inserted_econ,
            "earnings_new_rows": inserted_earn,
            "horizon_days": horizon_days,
            "window_end": end.isoformat(),
        },
    )
    return inserted_econ, inserted_earn
