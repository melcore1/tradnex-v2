"""Mock Exa client tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from shared.clients.exa_news import ExaArticle
from shared.clients.mock_exa_news import MockExaClient


@pytest.mark.asyncio
async def test_inject_article_roundtrip() -> None:
    client = MockExaClient(auto_seed=False)
    article = ExaArticle(
        title="NVDA pops on guidance",
        url="https://news.example.com/nvda-1",
        published_date=datetime.now(UTC),
        summary="Strong Q1 guidance.",
        score=Decimal("0.91"),
    )
    client.inject_article("NVDA", article)
    out = await client.fetch_news("NVDA", lookback_days=7, max_results=5)
    assert len(out) == 1
    assert out[0].title == "NVDA pops on guidance"


@pytest.mark.asyncio
async def test_clear_articles_resets() -> None:
    client = MockExaClient(auto_seed=True)
    out_before = await client.fetch_news("NVDA", lookback_days=30, max_results=10)
    assert len(out_before) > 0
    client.clear_articles()
    out_after = await client.fetch_news("NVDA", lookback_days=30, max_results=10)
    assert out_after == []


@pytest.mark.asyncio
async def test_auto_seed_includes_per_ticker_article() -> None:
    client = MockExaClient(auto_seed=True)
    out = await client.fetch_news("NVDA", lookback_days=7, max_results=3)
    assert len(out) >= 1
    out_amd = await client.fetch_news("AMD", lookback_days=7, max_results=3)
    assert len(out_amd) >= 1
    # Ensure tickers are case-insensitive
    out_lower = await client.fetch_news("nvda", lookback_days=7, max_results=3)
    assert len(out_lower) >= 1


@pytest.mark.asyncio
async def test_lookback_filter_excludes_old_articles() -> None:
    client = MockExaClient(auto_seed=False)
    old = ExaArticle(
        title="old news",
        url="https://news.example.com/old",
        published_date=datetime.now(UTC) - timedelta(days=30),
        summary="old",
    )
    fresh = ExaArticle(
        title="new news",
        url="https://news.example.com/new",
        published_date=datetime.now(UTC),
        summary="new",
    )
    client.inject_article("NVDA", old)
    client.inject_article("NVDA", fresh)
    out = await client.fetch_news("NVDA", lookback_days=7, max_results=10)
    titles = {a.title for a in out}
    assert "new news" in titles
    assert "old news" not in titles
