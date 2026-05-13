"""Phase 8.7: market_overview, regime_check, correlation_check, calendar_check, position_check."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from services.mcp.tools.calendar_check import calendar_check
from services.mcp.tools.correlation_check import correlation_check
from services.mcp.tools.market_overview import market_overview
from services.mcp.tools.position_check import position_check
from services.mcp.tools.regime_check import regime_check
from shared.clients.mock_market_data import MockDataClient
from tests._api_helpers import reset_modules_for_test_db
from tests._credential_helpers import TEST_ENCRYPTION_KEY


@pytest.fixture
def db_with_env(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    return reset_modules_for_test_db(tmp_path, monkeypatch)  # type: ignore[no-any-return]


@pytest.fixture
def mock_client() -> MockDataClient:
    return MockDataClient(seed=42)


# ---------- market_overview ----------


async def test_market_overview_stocks(mock_client: MockDataClient) -> None:
    result = await market_overview("stocks", mock_client)
    assert result["market_type"] == "stocks"
    assert len(result["most_active"]) == 10
    assert len(result["top_gainers"]) == 10
    assert len(result["top_losers"]) == 10


async def test_market_overview_crypto_returns_info_error(
    mock_client: MockDataClient,
) -> None:
    result = await market_overview("crypto", mock_client)
    assert "error" in result
    assert "crypto" in result["error"].lower()


# ---------- regime_check ----------


async def test_regime_check_returns_overall(
    db_with_env: sqlite3.Connection, mock_client: MockDataClient
) -> None:
    result = await regime_check("SPY", mock_client)
    assert "overall" in result
    assert "trend" in result
    assert "confidence" in result
    # mockdataclient should always have enough bars for regime
    assert result["ticker"] == "SPY"


# ---------- correlation_check ----------


async def test_correlation_check_pair_in_cache(
    db_with_env: sqlite3.Connection,
) -> None:
    # Seed two snapshot rows so the cached lookup succeeds.
    now_ts = datetime.now(UTC).timestamp()
    db_with_env.execute(
        "INSERT INTO correlation_snapshots (date, ticker_a, ticker_b, correlation, "
        "lookback_days, computed_ts) VALUES ('2026-05-12', 'SPY', 'QQQ', 0.85, 30, ?)",
        (now_ts,),
    )
    db_with_env.execute(
        "INSERT INTO correlation_snapshots (date, ticker_a, ticker_b, correlation, "
        "lookback_days, computed_ts) VALUES ('2026-05-12', 'QQQ', 'SPY', 0.85, 30, ?)",
        (now_ts,),
    )
    db_with_env.commit()
    result = await correlation_check("SPY", "QQQ")
    assert result["correlation"] == "0.85"
    assert "interpretation" in result
    assert "very strong" in result["interpretation"]


async def test_correlation_check_pair_missing_returns_note(
    db_with_env: sqlite3.Connection,
) -> None:
    result = await correlation_check("FOO", "BAR")
    assert result["correlation"] is None
    assert "note" in result


async def test_correlation_check_empty_cache_note_mentions_cli(
    db_with_env: sqlite3.Connection,
) -> None:
    """The empty-cache note must name the exact CLI to run, so a caller
    (e.g. Claude.ai) can surface an actionable recovery path instead of a
    generic "cache empty" message."""
    result = await correlation_check("SPY", "QQQ")
    assert result["correlation"] is None
    assert "note" in result
    # The literal CLI command must be in the note — if this drifts away
    # from the actual command, the message becomes useless.
    assert "compute-correlations" in result["note"]
    assert "universe" in result["note"]


async def test_correlation_check_symmetric(db_with_env: sqlite3.Connection) -> None:
    """Caller orders shouldn't matter — code checks both directions."""
    now_ts = datetime.now(UTC).timestamp()
    db_with_env.execute(
        "INSERT INTO correlation_snapshots (date, ticker_a, ticker_b, correlation, "
        "lookback_days, computed_ts) VALUES ('2026-05-12', 'SPY', 'IWM', 0.42, 30, ?)",
        (now_ts,),
    )
    db_with_env.commit()
    forward = await correlation_check("SPY", "IWM")
    backward = await correlation_check("IWM", "SPY")
    assert Decimal(forward["correlation"]) == Decimal(backward["correlation"])


# ---------- calendar_check ----------


async def test_calendar_check_empty_window(db_with_env: sqlite3.Connection) -> None:
    result = await calendar_check(days_ahead=7, ticker=None)
    assert result["count"] == 0
    assert result["events"] == []


async def test_calendar_check_empty_window_note_mentions_cli(
    db_with_env: sqlite3.Connection,
) -> None:
    """Empty result should include a note pointing at the refresh-calendar
    CLI so a 0-event window doesn't look like genuinely-no-news when the
    cache is just empty."""
    result = await calendar_check(days_ahead=14, ticker=None)
    assert result["count"] == 0
    assert "note" in result
    assert "refresh-calendar" in result["note"]


async def test_calendar_check_returns_seeded_events(
    db_with_env: sqlite3.Connection,
) -> None:
    future = (datetime.now(UTC) + timedelta(days=3)).timestamp()
    now_ts = datetime.now(UTC).timestamp()
    db_with_env.execute(
        "INSERT INTO calendar_cache (event_type, ticker, event_name, "
        "event_datetime_utc, impact, source, payload_json, fetched_ts) "
        "VALUES ('earnings', 'AAPL', 'AAPL Q2 earnings', ?, 'high', 'finnhub', '{}', ?)",
        (future, now_ts),
    )
    db_with_env.commit()
    result = await calendar_check(days_ahead=7, ticker="AAPL")
    assert result["count"] == 1
    assert result["events"][0]["ticker"] == "AAPL"
    assert result["events"][0]["impact"] == "high"


async def test_calendar_check_invalid_window_raises(
    db_with_env: sqlite3.Connection,
) -> None:
    with pytest.raises(ValueError, match="between"):
        await calendar_check(days_ahead=0, ticker=None)
    with pytest.raises(ValueError, match="between"):
        await calendar_check(days_ahead=200, ticker=None)


# ---------- position_check ----------


async def test_position_check_empty(db_with_env: sqlite3.Connection) -> None:
    result = await position_check()
    assert result["count"] == 0
    assert result["positions"] == []
    assert "note" in result


async def test_position_check_returns_open_position(
    db_with_env: sqlite3.Connection,
) -> None:
    now_ts = datetime.now(UTC).timestamp()
    db_with_env.execute(
        "INSERT INTO positions (candidate_id, ticker, contract_symbol, side, "
        "quantity, entry_price, entry_ts, status, strategy_name, entry_iv, "
        "entry_delta, entry_dte) "
        "VALUES (NULL, 'SPY', 'SPY  260516C00580000', 'long', 1, '5.50', ?, "
        "'open', 'long_options_momentum', '0.18', '0.45', 7)",
        (now_ts,),
    )
    db_with_env.commit()
    result = await position_check()
    assert result["count"] == 1
    pos = result["positions"][0]
    assert pos["ticker"] == "SPY"
    assert Decimal(pos["entry_price"]) == Decimal("5.50")
    assert pos["entry_dte"] == 7
