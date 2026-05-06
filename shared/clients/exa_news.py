"""Exa news feed: ABC + Pydantic model + real httpx-backed implementation.

Phase 5 uses Exa to pre-fetch news articles per ticker before each Claude
evaluation. Pre-fetch only — Claude does NOT call Exa via MCP. Articles
are embedded in the prompt JSON.

Network or rate-limit errors degrade gracefully: empty list returned + an
event emitted. Vetoes / orchestrator paths don't depend on news.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from shared.events import emit

SERVICE_NAME = "exa"
BASE_URL = "https://api.exa.ai"


class ExaArticle(BaseModel):
    """One article from Exa /search."""

    model_config = ConfigDict(frozen=True)

    title: str
    url: str
    published_date: datetime | None = None
    summary: str
    source: str = "exa"
    score: Decimal | None = None


class ExaClient(ABC):
    """Source of news articles per ticker."""

    @abstractmethod
    async def fetch_news(
        self,
        ticker: str,
        *,
        lookback_days: int,
        max_results: int,
    ) -> list[ExaArticle]: ...

    @abstractmethod
    async def health_check(self) -> bool: ...


def _parse_article(item: dict[str, Any]) -> ExaArticle | None:
    title = item.get("title")
    url = item.get("url")
    if not title or not url:
        return None

    raw_pub = item.get("publishedDate")
    pub: datetime | None = None
    if raw_pub:
        try:
            pub = datetime.fromisoformat(str(raw_pub).replace("Z", "+00:00"))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            pub = None

    text = item.get("text") or item.get("summary") or ""
    summary = text[:1000] if isinstance(text, str) else ""

    raw_score = item.get("score")
    score: Decimal | None = None
    if raw_score is not None:
        try:
            score = Decimal(str(raw_score))
        except (ValueError, TypeError):
            score = None

    return ExaArticle(
        title=str(title),
        url=str(url),
        published_date=pub,
        summary=summary,
        source="exa",
        score=score,
    )


class ExaNewsClient(ExaClient):
    """Real Exa /search implementation."""

    def __init__(self, api_key: str, *, timeout: float = 15.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    async def fetch_news(
        self,
        ticker: str,
        *,
        lookback_days: int,
        max_results: int,
    ) -> list[ExaArticle]:
        start_date = (datetime.now(UTC) - timedelta(days=lookback_days)).date()
        body = {
            "query": f"{ticker} stock news catalysts",
            "type": "neural",
            "numResults": max_results,
            "useAutoprompt": True,
            "startPublishedDate": start_date.isoformat(),
            "contents": {"text": {"maxCharacters": 1000}},
        }
        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    BASE_URL + "/search", json=body, headers=headers
                )
            if resp.status_code == 429:
                emit(SERVICE_NAME, "warn", "exa_rate_limited", {"ticker": ticker})
                return []
            if resp.status_code >= 400:
                emit(
                    SERVICE_NAME,
                    "error",
                    "exa_http_error",
                    {"ticker": ticker, "status": resp.status_code},
                )
                return []
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            emit(
                SERVICE_NAME,
                "error",
                "exa_fetch_error",
                {"ticker": ticker, "error": str(e)[:200]},
            )
            return []

        results = data.get("results") or []
        out: list[ExaArticle] = []
        for item in results:
            art = _parse_article(item)
            if art is not None:
                out.append(art)
        return out[:max_results]

    async def health_check(self) -> bool:
        return bool(self._api_key)
