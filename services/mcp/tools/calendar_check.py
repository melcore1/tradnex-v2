"""calendar_check — upcoming economic/earnings events from the cache.

Reads ``calendar_cache`` (populated nightly via Finnhub). Window is
configurable; defaults to 14 days ahead. Optional ticker filter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from services.mcp.deps import db_session
from shared.services.calendar_service import CalendarService


async def calendar_check(
    days_ahead: int,
    ticker: str | None,
) -> dict[str, Any]:
    """Return events in the configured window."""
    if days_ahead < 1 or days_ahead > 90:
        raise ValueError("days_ahead must be between 1 and 90")

    start = datetime.now(UTC)
    end = start + timedelta(days=days_ahead)

    with db_session() as conn:
        service = CalendarService(conn)
        events = await service.get_events_in_window(
            start=start,
            end=end,
            ticker=ticker.upper() if ticker else None,
        )

    return {
        "events": [
            {
                "type": ev.event_type,
                "name": ev.event_name,
                "ticker": ev.ticker,
                "datetime_utc": ev.event_datetime_utc.isoformat(),
                "hours_until": str(ev.hours_until),
                "impact": ev.impact,
                "source": ev.source,
            }
            for ev in events
        ],
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "count": len(events),
    }
