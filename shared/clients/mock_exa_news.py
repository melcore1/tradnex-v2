"""In-memory mock Exa client. Used in dev when no EXA_API_KEY and in tests
to inject specific articles for prompt-builder verification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from shared.clients.exa_news import ExaArticle, ExaClient
from shared.clients.mock_market_data import DEFAULT_BASELINES


class MockExaClient(ExaClient):
    """Auto-seeds one generic article per baseline ticker dated 2 days ago.

    Tests can `inject_article(article)` for specific scenarios or
    `clear_articles()` to start clean.
    """

    def __init__(self, *, auto_seed: bool = True) -> None:
        self._articles: dict[str, list[ExaArticle]] = {}
        if auto_seed:
            self._auto_seed()

    def _auto_seed(self) -> None:
        two_days_ago = datetime.now(UTC) - timedelta(days=2)
        for ticker in DEFAULT_BASELINES:
            self._articles[ticker.upper()] = [
                ExaArticle(
                    title=f"{ticker} announces quarterly update",
                    url=f"https://mock.example.com/{ticker.lower()}-news",
                    published_date=two_days_ago,
                    summary=(
                        f"{ticker} reported in-line guidance with no major "
                        f"surprises. Mock article for dev/testing."
                    ),
                    source="mock",
                    score=Decimal("0.65"),
                )
            ]

    def inject_article(self, ticker: str, article: ExaArticle) -> None:
        key = ticker.upper()
        self._articles.setdefault(key, []).append(article)

    def clear_articles(self) -> None:
        self._articles.clear()

    async def fetch_news(
        self,
        ticker: str,
        *,
        lookback_days: int,
        max_results: int,
    ) -> list[ExaArticle]:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        items = self._articles.get(ticker.upper(), [])
        in_window = [
            a for a in items
            if a.published_date is None or a.published_date >= cutoff
        ]
        return in_window[:max_results]

    async def health_check(self) -> bool:
        return True
