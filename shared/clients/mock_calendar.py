"""In-memory mock calendar feed. Used in dev when no FINNHUB_API_KEY,
and in tests to inject specific events."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from shared.clients.calendar_feed import CalendarEvent, CalendarFeed
from shared.clients.mock_market_data import DEFAULT_BASELINES

ET = ZoneInfo("America/New_York")


def _et_to_utc(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=ET).astimezone(UTC)


class MockCalendarClient(CalendarFeed):
    def __init__(self, *, auto_seed: bool = True) -> None:
        self._events: list[CalendarEvent] = []
        if auto_seed:
            self._auto_seed()

    def inject_event(self, event: CalendarEvent) -> None:
        self._events.append(event)

    def clear_events(self) -> None:
        self._events.clear()

    def _auto_seed(self) -> None:
        today = datetime.now(UTC).date()

        # FOMC ~6 weeks out at 14:00 ET
        fomc_date = today + timedelta(days=42)
        self._events.append(
            CalendarEvent(
                event_type="economic",
                ticker=None,
                event_name="FOMC Rate Decision",
                event_datetime_utc=_et_to_utc(fomc_date, time(14, 0)),
                impact="high",
                source="mock",
                payload={"country": "US"},
            )
        )

        # CPI 2-4 weeks out at 08:30 ET
        cpi_date = today + timedelta(days=14)
        self._events.append(
            CalendarEvent(
                event_type="economic",
                ticker=None,
                event_name="US CPI Release",
                event_datetime_utc=_et_to_utc(cpi_date, time(8, 30)),
                impact="high",
                source="mock",
                payload={"country": "US"},
            )
        )

        # NFP next first Friday at 08:30 ET
        nfp_date = self._next_first_friday(today)
        self._events.append(
            CalendarEvent(
                event_type="economic",
                ticker=None,
                event_name="US Nonfarm Payrolls",
                event_datetime_utc=_et_to_utc(nfp_date, time(8, 30)),
                impact="high",
                source="mock",
                payload={"country": "US"},
            )
        )

        # Earnings: each baseline ticker at a stable per-ticker offset
        for i, ticker in enumerate(DEFAULT_BASELINES):
            offset = 30 + (i * 3)  # 30, 33, 36, ... days
            earn_date = today + timedelta(days=offset)
            self._events.append(
                CalendarEvent(
                    event_type="earnings",
                    ticker=ticker,
                    event_name=f"{ticker} Quarterly Earnings",
                    event_datetime_utc=_et_to_utc(earn_date, time(16, 0)),
                    impact="high",
                    source="mock",
                    payload={"period": "Q1 2026"},
                )
            )

    @staticmethod
    def _next_first_friday(d: date) -> date:
        # Find the first Friday of next month if we're past today's first
        # Friday in the current month, else current month's first Friday.
        first_of_month = date(d.year, d.month, 1)
        offset = (4 - first_of_month.weekday()) % 7
        first_fri = first_of_month + timedelta(days=offset)
        if first_fri >= d:
            return first_fri
        # Next month
        next_month = d.month + 1
        next_year = d.year + (1 if next_month > 12 else 0)
        next_month = ((next_month - 1) % 12) + 1
        first_of_next = date(next_year, next_month, 1)
        offset2 = (4 - first_of_next.weekday()) % 7
        return first_of_next + timedelta(days=offset2)

    async def fetch_economic_calendar(
        self, start: date, end: date
    ) -> list[CalendarEvent]:
        start_dt = datetime.combine(start, time.min, tzinfo=UTC)
        end_dt = datetime.combine(end, time.max, tzinfo=UTC)
        return [
            e
            for e in self._events
            if e.event_type == "economic"
            and start_dt <= e.event_datetime_utc <= end_dt
        ]

    async def fetch_earnings_calendar(
        self,
        start: date,
        end: date,
        tickers: list[str] | None = None,
    ) -> list[CalendarEvent]:
        upper_set = {t.upper() for t in tickers} if tickers else None
        start_dt = datetime.combine(start, time.min, tzinfo=UTC)
        end_dt = datetime.combine(end, time.max, tzinfo=UTC)
        return [
            e
            for e in self._events
            if e.event_type == "earnings"
            and start_dt <= e.event_datetime_utc <= end_dt
            and (upper_set is None or (e.ticker and e.ticker.upper() in upper_set))
        ]

    async def health_check(self) -> bool:
        return True
