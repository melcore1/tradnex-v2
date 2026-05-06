"""Finnhub-backed calendar client. Free-tier endpoints:
    /calendar/economic?from=YYYY-MM-DD&to=YYYY-MM-DD&token=<key>
    /calendar/earnings?from=YYYY-MM-DD&to=YYYY-MM-DD&token=<key>

Network or rate-limit errors degrade gracefully — the function returns []
and emits an event. Vetoes read from the cached `calendar_cache` table,
so a transient outage doesn't break orchestration.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

import httpx

from shared.clients.calendar_feed import CalendarEvent, CalendarFeed, ImpactLevel
from shared.events import emit

SERVICE_NAME = "calendar"
BASE_URL = "https://finnhub.io/api/v1"


def _normalize_impact(raw: Any) -> ImpactLevel:
    """Finnhub returns 'low'/'medium'/'high' or sometimes numeric 0..3."""
    if isinstance(raw, str):
        s = raw.lower().strip()
        if s in ("low", "medium", "high"):
            return s  # type: ignore[return-value]
    if isinstance(raw, int | float):
        if raw >= 3:
            return "high"
        if raw >= 2:
            return "medium"
        if raw >= 1:
            return "low"
    return "unknown"


def _parse_economic_event(item: dict[str, Any]) -> CalendarEvent | None:
    country = item.get("country")
    if country != "US":
        return None
    name = item.get("event") or "Unnamed economic event"
    raw_time = item.get("time") or item.get("date")
    if not raw_time:
        return None
    try:
        if "T" in str(raw_time):
            dt = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
        elif " " in str(raw_time):
            dt = datetime.strptime(str(raw_time), "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = datetime.strptime(str(raw_time), "%Y-%m-%d")
            dt = dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None
    return CalendarEvent(
        event_type="economic",
        ticker=None,
        event_name=name,
        event_datetime_utc=dt.astimezone(UTC),
        impact=_normalize_impact(item.get("impact")),
        source="finnhub",
        payload=item,
    )


def _parse_earnings_event(item: dict[str, Any]) -> CalendarEvent | None:
    symbol = item.get("symbol")
    if not symbol:
        return None
    raw_date = item.get("date")
    if not raw_date:
        return None
    try:
        d = datetime.strptime(str(raw_date), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    raw_hour = item.get("hour")
    if raw_hour == "bmo":
        from datetime import time

        dt = datetime.combine(d, time(8, 0), tzinfo=UTC)
    elif raw_hour == "amc":
        from datetime import time

        dt = datetime.combine(d, time(20, 0), tzinfo=UTC)
    else:
        from datetime import time

        dt = datetime.combine(d, time(16, 0), tzinfo=UTC)
    return CalendarEvent(
        event_type="earnings",
        ticker=str(symbol).upper(),
        event_name=f"{symbol} Quarterly Earnings",
        event_datetime_utc=dt,
        impact="high",
        source="finnhub",
        payload=item,
    )


class FinnhubCalendarClient(CalendarFeed):
    def __init__(self, api_key: str, *, timeout: float = 10.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    async def _get(
        self,
        path: Literal["/calendar/economic", "/calendar/earnings"],
        *,
        start: date,
        end: date,
    ) -> dict[str, Any]:
        params = {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "token": self._api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(BASE_URL + path, params=params)
            if resp.status_code == 429:
                emit(SERVICE_NAME, "warn", "calendar_rate_limited", {"path": path})
                return {}
            if resp.status_code >= 400:
                emit(
                    SERVICE_NAME,
                    "error",
                    "calendar_http_error",
                    {"path": path, "status": resp.status_code},
                )
                return {}
            return resp.json()  # type: ignore[no-any-return]
        except (httpx.HTTPError, ValueError) as e:
            emit(
                SERVICE_NAME,
                "error",
                "calendar_fetch_error",
                {"path": path, "error": str(e)[:200]},
            )
            return {}

    async def fetch_economic_calendar(
        self, start: date, end: date
    ) -> list[CalendarEvent]:
        data = await self._get("/calendar/economic", start=start, end=end)
        events_raw = data.get("economicCalendar") or []
        out: list[CalendarEvent] = []
        for item in events_raw:
            ev = _parse_economic_event(item)
            if ev is not None:
                out.append(ev)
        return out

    async def fetch_earnings_calendar(
        self,
        start: date,
        end: date,
        tickers: list[str] | None = None,
    ) -> list[CalendarEvent]:
        data = await self._get("/calendar/earnings", start=start, end=end)
        events_raw = data.get("earningsCalendar") or []
        out: list[CalendarEvent] = []
        upper = {t.upper() for t in tickers} if tickers else None
        for item in events_raw:
            ev = _parse_earnings_event(item)
            if ev is None:
                continue
            if upper is not None and (ev.ticker is None or ev.ticker not in upper):
                continue
            out.append(ev)
        return out

    async def health_check(self) -> bool:
        return bool(self._api_key)
