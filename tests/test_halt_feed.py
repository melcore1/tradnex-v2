"""Halt feed tests: MockHaltFeed, NasdaqHaltFeed (RSS fixture), factory."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from shared.clients.factory import make_halt_feed
from shared.clients.halt_feed import Halt
from shared.clients.mock_halt_feed import MockHaltFeed
from shared.clients.nasdaq_halt_feed import NasdaqHaltFeed, _parse_halt_entry
from shared.config import Settings


def _halt(ticker: str, active: bool = True, hours_ago: int = 0) -> Halt:
    return Halt(
        ticker=ticker,
        halt_time=datetime.now(UTC) - timedelta(hours=hours_ago),
        halt_reason="T1 - News Pending",
        halt_code="T1",
        is_active=active,
    )


async def test_mock_inject_and_get_active() -> None:
    feed = MockHaltFeed()
    feed.inject_halt(_halt("AAA"))
    feed.inject_halt(_halt("BBB", active=False, hours_ago=2))
    active = await feed.get_active_halts()
    assert len(active) == 1
    assert active[0].ticker == "AAA"


async def test_mock_clear_halts() -> None:
    feed = MockHaltFeed()
    feed.inject_halt(_halt("AAA"))
    feed.clear_halts()
    assert await feed.get_active_halts() == []


async def test_mock_resolve_halt() -> None:
    feed = MockHaltFeed()
    feed.inject_halt(_halt("AAA"))
    feed.resolve_halt("AAA", datetime.now(UTC))
    active = await feed.get_active_halts()
    assert active == []
    recent = await feed.get_recent_halts(hours=24)
    assert len(recent) == 1
    assert recent[0].is_active is False
    assert recent[0].resumption_time is not None


async def test_mock_is_halted() -> None:
    feed = MockHaltFeed()
    feed.inject_halt(_halt("AAA"))
    assert await feed.is_halted("AAA") is True
    assert await feed.is_halted("ZZZ") is False
    assert await feed.is_halted("aaa") is True  # case-insensitive


async def test_mock_health_check() -> None:
    feed = MockHaltFeed()
    assert await feed.health_check() is True


def test_nasdaq_parse_entry_extracts_ticker_and_code() -> None:
    fixture = Path(__file__).parent / "fixtures" / "nasdaq_halts_sample.xml"
    import feedparser

    feed = feedparser.parse(fixture.read_text())
    halts = [_parse_halt_entry(e) for e in feed.entries]
    halts = [h for h in halts if h is not None]
    assert len(halts) == 2
    tickers = {h.ticker for h in halts}
    assert tickers == {"TESTA", "TESTB"}
    assert any(h.halt_code == "T1" for h in halts)
    assert any(h.halt_code == "LUDP" for h in halts)


def test_nasdaq_parse_returns_none_on_garbage() -> None:
    class FakeEntry:
        summary = ""
        title = ""
        published_parsed = None

    assert _parse_halt_entry(FakeEntry()) is None


async def test_nasdaq_network_error_returns_cached() -> None:
    feed = NasdaqHaltFeed(poll_interval_seconds=1)
    feed._cache = [_halt("CACHED")]
    feed._last_fetched = datetime.now(UTC) - timedelta(seconds=10)

    async def _raise(*_args, **_kwargs):
        raise httpx_RuntimeError("network down")

    with patch("shared.clients.nasdaq_halt_feed.httpx.AsyncClient") as mock_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        mock_class.return_value = mock_client
        active = await feed.get_active_halts()
    # Should have returned stale cache, not crashed
    assert len(active) == 1
    assert active[0].ticker == "CACHED"


class httpx_RuntimeError(Exception):
    """Stand-in for any httpx error during the test."""


def test_factory_dispatches_mock() -> None:
    settings = Settings.model_construct(
        DATABASE_PATH="/tmp/x.db",
        HALT_FEED="mock",
    )
    feed = make_halt_feed(settings)
    assert isinstance(feed, MockHaltFeed)


def test_factory_dispatches_nasdaq() -> None:
    settings = Settings.model_construct(
        DATABASE_PATH="/tmp/x.db",
        HALT_FEED="nasdaq",
        HALT_POLL_MARKET_SECONDS=30,
    )
    feed = make_halt_feed(settings)
    assert isinstance(feed, NasdaqHaltFeed)


def test_factory_invalid_raises() -> None:
    settings = Settings.model_construct(
        DATABASE_PATH="/tmp/x.db",
        HALT_FEED="bogus",  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="Unknown HALT_FEED"):
        make_halt_feed(settings)


def test_halt_model_validates_required_fields() -> None:
    h = Halt(
        ticker="AAA",
        halt_time=datetime.now(UTC),
        halt_reason="reason",
        halt_code="T1",
        is_active=True,
    )
    assert h.exchange == "NASDAQ"  # default
