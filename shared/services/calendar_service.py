"""Calendar read-side: queries calendar_cache + an upsert helper.

Vetoes call CalendarService methods. The nightly refresh task calls
`upsert_event` to populate the cache from Finnhub or the mock client.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from shared.clients.calendar_feed import CalendarEvent, EventType, ImpactLevel

_IMPACT_RANK: dict[str, int] = {
    "unknown": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}


def _row_to_event(row: sqlite3.Row) -> CalendarEvent:
    payload_raw = row["payload_json"]
    payload = json.loads(payload_raw) if payload_raw else {}
    # Empty string is stored for "no ticker" so the UNIQUE constraint can
    # actually deduplicate across runs (SQLite treats NULLs as distinct).
    raw_ticker = row["ticker"]
    ticker = raw_ticker if raw_ticker not in (None, "") else None
    return CalendarEvent(
        event_type=row["event_type"],
        ticker=ticker,
        event_name=row["event_name"],
        event_datetime_utc=datetime.fromtimestamp(
            float(row["event_datetime_utc"]), UTC
        ),
        impact=row["impact"] or "unknown",
        source=row["source"],
        payload=payload,
    )


class CalendarService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    async def get_events_in_window(
        self,
        start: datetime,
        end: datetime,
        *,
        event_type: EventType | None = None,
        ticker: str | None = None,
        impact_min: ImpactLevel = "low",
    ) -> list[CalendarEvent]:
        sql = (
            "SELECT id, event_type, ticker, event_name, event_datetime_utc, "
            "impact, source, payload_json FROM calendar_cache "
            "WHERE event_datetime_utc >= ? AND event_datetime_utc <= ?"
        )
        params: list[Any] = [start.timestamp(), end.timestamp()]
        if event_type is not None:
            sql += " AND event_type = ?"
            params.append(event_type)
        if ticker is not None:
            sql += " AND ticker = ?"
            params.append(ticker.upper())
        sql += " ORDER BY event_datetime_utc ASC"
        rows = self._conn.execute(sql, params).fetchall()
        min_rank = _IMPACT_RANK[impact_min]
        out: list[CalendarEvent] = []
        for r in rows:
            ev = _row_to_event(r)
            if _IMPACT_RANK.get(ev.impact, 0) < min_rank:
                continue
            out.append(ev)
        return out

    async def has_high_impact_within(
        self,
        hours: int,
        *,
        event_type: EventType | None = None,
        ticker: str | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        end = datetime.fromtimestamp(now.timestamp() + hours * 3600, UTC)
        events = await self.get_events_in_window(
            now,
            end,
            event_type=event_type,
            ticker=ticker,
            impact_min="high",
        )
        return len(events) > 0

    async def get_next_earnings(self, ticker: str) -> CalendarEvent | None:
        now = datetime.now(UTC)
        row = self._conn.execute(
            "SELECT id, event_type, ticker, event_name, event_datetime_utc, "
            "impact, source, payload_json FROM calendar_cache "
            "WHERE event_type = 'earnings' AND ticker = ? "
            "AND event_datetime_utc >= ? "
            "ORDER BY event_datetime_utc ASC LIMIT 1",
            (ticker.upper(), now.timestamp()),
        ).fetchone()
        if row is None:
            return None
        return _row_to_event(row)

    @staticmethod
    async def upsert_event(
        conn: sqlite3.Connection, event: CalendarEvent
    ) -> int:
        """Insert or replace via the UNIQUE constraint. Returns 1 if a new row
        was inserted, 0 if an existing row was replaced."""
        before = int(conn.execute("SELECT COUNT(*) FROM calendar_cache").fetchone()[0])
        # Store '' for null tickers so SQLite UNIQUE actually dedupes
        # (NULL != NULL by default).
        ticker_for_db = event.ticker if event.ticker is not None else ""
        conn.execute(
            "INSERT INTO calendar_cache "
            "(event_type, ticker, event_name, event_datetime_utc, impact, "
            "source, payload_json, fetched_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(event_type, ticker, event_name, event_datetime_utc) "
            "DO UPDATE SET impact = excluded.impact, "
            "source = excluded.source, payload_json = excluded.payload_json, "
            "fetched_ts = excluded.fetched_ts",
            (
                event.event_type,
                ticker_for_db,
                event.event_name,
                event.event_datetime_utc.timestamp(),
                event.impact,
                event.source,
                json.dumps(event.payload, default=str),
                datetime.now(UTC).timestamp(),
            ),
        )
        conn.commit()
        after = int(conn.execute("SELECT COUNT(*) FROM calendar_cache").fetchone()[0])
        return after - before
