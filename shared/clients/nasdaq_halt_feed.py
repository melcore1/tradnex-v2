"""NASDAQ trading halt RSS feed (https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import feedparser
import httpx

from shared.clients.halt_feed import Halt, HaltFeed
from shared.events import emit

NASDAQ_HALTS_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"
SERVICE_NAME = "data"


def _parse_halt_entry(entry: Any) -> Halt | None:
    try:
        if hasattr(entry, "get"):
            summary = entry.get("summary", "")
            title = entry.get("title", "")
        else:
            summary = getattr(entry, "summary", "")
            title = getattr(entry, "title", "")

        ticker_match = re.search(r"Issue Symbol[^A-Z0-9]*([A-Z][A-Z0-9.\-]*)", summary)
        if not ticker_match:
            ticker_match = re.search(r"\b([A-Z][A-Z0-9]{0,5})\b", title)
        if not ticker_match:
            return None
        ticker = ticker_match.group(1)

        code_match = re.search(r"Halt Reason\s*Code[^A-Z]*([A-Z0-9]+)", summary)
        halt_code = code_match.group(1) if code_match else "UNKNOWN"
        reason_match = re.search(r"Halt Reason\s*Code[^:]*:\s*([^<\n]+)", summary)
        halt_reason = reason_match.group(1).strip() if reason_match else halt_code

        published = getattr(entry, "published_parsed", None)
        if published is not None:
            halt_time = datetime(
                published[0],
                published[1],
                published[2],
                published[3],
                published[4],
                published[5],
                tzinfo=UTC,
            )
        else:
            halt_time = datetime.now(UTC)

        resumption_match = re.search(r"Resumption Time[^:]*:\s*([\d:\-/ ]+)", summary)
        resumption_time: datetime | None = None
        if resumption_match:
            try:
                txt = resumption_match.group(1).strip()
                resumption_time = datetime.fromisoformat(txt).replace(tzinfo=UTC)
            except ValueError:
                resumption_time = None

        is_active = resumption_time is None or resumption_time > datetime.now(UTC)

        return Halt(
            ticker=ticker,
            halt_time=halt_time,
            halt_reason=halt_reason,
            halt_code=halt_code,
            resumption_time=resumption_time,
            is_active=is_active,
            exchange="NASDAQ",
        )
    except Exception:
        return None


class NasdaqHaltFeed(HaltFeed):
    def __init__(
        self,
        url: str = NASDAQ_HALTS_URL,
        poll_interval_seconds: int = 30,
        timeout_seconds: int = 10,
    ) -> None:
        self._url = url
        self._poll_interval = timedelta(seconds=poll_interval_seconds)
        self._timeout = timeout_seconds
        self._cache: list[Halt] = []
        self._last_fetched: datetime | None = None

    async def _refresh_if_stale(self) -> None:
        now = datetime.now(UTC)
        if (
            self._last_fetched is not None
            and now - self._last_fetched < self._poll_interval
        ):
            return
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(self._url)
                response.raise_for_status()
                feed = feedparser.parse(response.text)
            halts: list[Halt] = []
            for entry in feed.entries:
                halt = _parse_halt_entry(entry)
                if halt is not None:
                    halts.append(halt)
            self._cache = halts
            self._last_fetched = now
        except Exception as e:
            emit(
                SERVICE_NAME,
                "warn",
                "halt_feed_fetch_failed",
                {"url": self._url, "error": str(e)[:200]},
            )

    async def get_active_halts(self) -> list[Halt]:
        await self._refresh_if_stale()
        return [h for h in self._cache if h.is_active]

    async def get_recent_halts(self, hours: int = 24) -> list[Halt]:
        await self._refresh_if_stale()
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        return [h for h in self._cache if h.halt_time >= cutoff]

    async def is_halted(self, ticker: str) -> bool:
        await self._refresh_if_stale()
        ticker_u = ticker.upper()
        return any(h.is_active and h.ticker == ticker_u for h in self._cache)

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.head(self._url)
                return response.status_code < 500
        except Exception:
            return False
