"""Real ExaNewsClient tests with mocked httpx."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from shared.clients.exa_news import ExaNewsClient


@pytest.fixture
def client() -> ExaNewsClient:
    return ExaNewsClient(api_key="test-key")


def _mock_response(json_data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=json_data)
    return resp


@pytest.mark.asyncio
async def test_search_parses_articles(client: ExaNewsClient) -> None:
    payload = {
        "results": [
            {
                "title": "NVDA earnings beat",
                "url": "https://news.example.com/1",
                "publishedDate": "2026-05-04T12:00:00Z",
                "text": "NVDA beat estimates by ...",
                "score": 0.85,
            },
            {
                "title": "Sell-side coverage",
                "url": "https://news.example.com/2",
                "publishedDate": "2026-05-03T08:00:00Z",
                "text": "Analyst initiates with buy.",
                "score": 0.71,
            },
        ]
    }
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(
        return_value=MagicMock(post=AsyncMock(return_value=_mock_response(payload)))
    )
    fake_cm.__aexit__ = AsyncMock(return_value=None)
    with patch("shared.clients.exa_news.httpx.AsyncClient", return_value=fake_cm):
        out = await client.fetch_news(
            "NVDA", lookback_days=7, max_results=5
        )
    assert len(out) == 2
    assert out[0].title == "NVDA earnings beat"
    assert out[0].published_date is not None
    assert out[0].published_date.tzinfo is not None
    assert out[0].score is not None
    assert float(out[0].score) == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_max_results_caps_output(client: ExaNewsClient) -> None:
    payload = {
        "results": [
            {"title": f"a-{i}", "url": f"https://e.com/{i}"}
            for i in range(10)
        ]
    }
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(
        return_value=MagicMock(post=AsyncMock(return_value=_mock_response(payload)))
    )
    fake_cm.__aexit__ = AsyncMock(return_value=None)
    with patch("shared.clients.exa_news.httpx.AsyncClient", return_value=fake_cm):
        out = await client.fetch_news(
            "NVDA", lookback_days=7, max_results=3
        )
    assert len(out) == 3


@pytest.mark.asyncio
async def test_network_error_returns_empty(client: ExaNewsClient) -> None:
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(
        return_value=MagicMock(
            post=AsyncMock(side_effect=httpx.ConnectError("boom"))
        )
    )
    fake_cm.__aexit__ = AsyncMock(return_value=None)
    with patch("shared.clients.exa_news.httpx.AsyncClient", return_value=fake_cm):
        out = await client.fetch_news("NVDA", lookback_days=7, max_results=3)
    assert out == []


@pytest.mark.asyncio
async def test_rate_limit_returns_empty(client: ExaNewsClient) -> None:
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(
        return_value=MagicMock(
            post=AsyncMock(return_value=_mock_response({}, status=429))
        )
    )
    fake_cm.__aexit__ = AsyncMock(return_value=None)
    with patch("shared.clients.exa_news.httpx.AsyncClient", return_value=fake_cm):
        out = await client.fetch_news("NVDA", lookback_days=7, max_results=3)
    assert out == []


# Avoid unused-import warning
_ = date
