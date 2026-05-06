"""Finnhub calendar client tests with mocked HTTP."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from shared.clients.finnhub_calendar import FinnhubCalendarClient


@pytest.fixture
def client():
    return FinnhubCalendarClient(api_key="test-key")


def _mock_response(json_data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=json_data)
    return resp


@pytest.mark.asyncio
async def test_economic_calendar_parses_us_events(client) -> None:
    payload = {
        "economicCalendar": [
            {
                "country": "US",
                "event": "FOMC Rate Decision",
                "time": "2026-05-15 18:00:00",
                "impact": "high",
            },
            {
                "country": "EU",
                "event": "ECB Press Conference",
                "time": "2026-05-15 12:00:00",
                "impact": "high",
            },
            {
                "country": "US",
                "event": "CPI",
                "time": "2026-05-12 12:30:00",
                "impact": "medium",
            },
        ]
    }
    fake_client_cm = MagicMock()
    fake_client_cm.__aenter__ = AsyncMock(
        return_value=MagicMock(get=AsyncMock(return_value=_mock_response(payload)))
    )
    fake_client_cm.__aexit__ = AsyncMock(return_value=None)
    with patch("shared.clients.finnhub_calendar.httpx.AsyncClient", return_value=fake_client_cm):
        events = await client.fetch_economic_calendar(date(2026, 5, 1), date(2026, 5, 31))
    # EU event filtered out; only US events parsed
    assert len(events) == 2
    assert {e.event_name for e in events} == {"FOMC Rate Decision", "CPI"}


@pytest.mark.asyncio
async def test_earnings_calendar_parses(client) -> None:
    payload = {
        "earningsCalendar": [
            {"symbol": "NVDA", "date": "2026-05-20", "hour": "amc"},
            {"symbol": "AMD", "date": "2026-05-15", "hour": "bmo"},
        ]
    }
    fake_client_cm = MagicMock()
    fake_client_cm.__aenter__ = AsyncMock(
        return_value=MagicMock(get=AsyncMock(return_value=_mock_response(payload)))
    )
    fake_client_cm.__aexit__ = AsyncMock(return_value=None)
    with patch("shared.clients.finnhub_calendar.httpx.AsyncClient", return_value=fake_client_cm):
        events = await client.fetch_earnings_calendar(
            date(2026, 5, 1), date(2026, 5, 31), tickers=["NVDA", "AMD"]
        )
    assert len(events) == 2
    nvda = next(e for e in events if e.ticker == "NVDA")
    assert nvda.event_datetime_utc.hour == 20  # amc
    amd = next(e for e in events if e.ticker == "AMD")
    assert amd.event_datetime_utc.hour == 8  # bmo


@pytest.mark.asyncio
async def test_network_error_returns_empty(client) -> None:
    fake_client_cm = MagicMock()
    fake_client_cm.__aenter__ = AsyncMock(
        return_value=MagicMock(get=AsyncMock(side_effect=httpx.ConnectError("boom")))
    )
    fake_client_cm.__aexit__ = AsyncMock(return_value=None)
    with patch("shared.clients.finnhub_calendar.httpx.AsyncClient", return_value=fake_client_cm):
        events = await client.fetch_economic_calendar(date(2026, 5, 1), date(2026, 5, 5))
    assert events == []


@pytest.mark.asyncio
async def test_rate_limit_returns_empty(client) -> None:
    fake_client_cm = MagicMock()
    fake_client_cm.__aenter__ = AsyncMock(
        return_value=MagicMock(get=AsyncMock(return_value=_mock_response({}, status=429)))
    )
    fake_client_cm.__aexit__ = AsyncMock(return_value=None)
    with patch("shared.clients.finnhub_calendar.httpx.AsyncClient", return_value=fake_client_cm):
        events = await client.fetch_economic_calendar(date(2026, 5, 1), date(2026, 5, 5))
    assert events == []
