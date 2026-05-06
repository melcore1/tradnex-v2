"""Tests for SchwabDataClient mapping logic.

Uses unittest.mock to inject a stand-in for schwab-py's AsyncClient via the
private `_client=` constructor kwarg. This validates JSON → Pydantic mapping
and HTTP-status → exception mapping without making real network calls or
requiring credentials.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from shared.clients.schwab_market_data import (
    SchwabApiError,
    SchwabAuthRequired,
    SchwabDataClient,
    SchwabRateLimited,
)


def _make_response(status: int, body: dict[str, Any] | list[Any]) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status
    response.json = MagicMock(return_value=body)
    response.text = str(body)
    return response


def _client_with(mock_async_client: AsyncMock) -> SchwabDataClient:
    return SchwabDataClient(_client=mock_async_client)


SAMPLE_QUOTE_RESPONSE = {
    "AAPL": {
        "quote": {
            "lastPrice": 228.50,
            "bidPrice": 228.45,
            "askPrice": 228.55,
            "bidSize": 5,
            "askSize": 7,
            "openPrice": 228.00,
            "highPrice": 230.00,
            "lowPrice": 227.00,
            "closePrice": 226.50,
            "totalVolume": 50_000_000,
        },
        "fundamental": {
            "avg30DaysVolume": 45_000_000,
        },
    }
}


async def test_get_quote_maps_response_correctly() -> None:
    mock = AsyncMock()
    mock.get_quote = AsyncMock(return_value=_make_response(200, SAMPLE_QUOTE_RESPONSE))
    client = _client_with(mock)

    quote = await client.get_quote("AAPL")
    assert quote.ticker == "AAPL"
    assert quote.spot == Decimal("228.5")
    assert quote.bid == Decimal("228.45")
    assert quote.ask == Decimal("228.55")
    assert quote.bid_size == 5
    assert quote.day_high == Decimal("230.0")
    assert quote.prev_close == Decimal("226.5")
    assert quote.volume == 50_000_000
    assert quote.avg_volume_30d == 45_000_000


async def test_get_quote_handles_missing_bid_ask_outside_market_hours() -> None:
    response_body = {
        "AAPL": {
            "quote": {
                "lastPrice": 228.50,
                "closePrice": 226.50,
            },
            "fundamental": {},
        }
    }
    mock = AsyncMock()
    mock.get_quote = AsyncMock(return_value=_make_response(200, response_body))
    client = _client_with(mock)

    quote = await client.get_quote("AAPL")
    # Falls back to lastPrice when bid/ask absent
    assert quote.bid == Decimal("228.5")
    assert quote.ask == Decimal("228.5")
    assert quote.bid_size == 0


async def test_get_quote_401_raises_auth_required() -> None:
    mock = AsyncMock()
    mock.get_quote = AsyncMock(return_value=_make_response(401, {"error": "unauthorized"}))
    client = _client_with(mock)
    with pytest.raises(SchwabAuthRequired):
        await client.get_quote("AAPL")


async def test_get_quote_429_raises_rate_limited() -> None:
    mock = AsyncMock()
    mock.get_quote = AsyncMock(return_value=_make_response(429, {"error": "throttled"}))
    client = _client_with(mock)
    with pytest.raises(SchwabRateLimited):
        await client.get_quote("AAPL")


async def test_get_quote_500_raises_api_error() -> None:
    mock = AsyncMock()
    mock.get_quote = AsyncMock(return_value=_make_response(500, {"error": "boom"}))
    client = _client_with(mock)
    with pytest.raises(SchwabApiError):
        await client.get_quote("AAPL")


async def test_get_quotes_returns_dict_keyed_by_uppercase_ticker() -> None:
    mock = AsyncMock()
    mock.get_quotes = AsyncMock(return_value=_make_response(200, SAMPLE_QUOTE_RESPONSE))
    client = _client_with(mock)
    result = await client.get_quotes(["aapl"])
    assert "AAPL" in result
    assert result["AAPL"].spot == Decimal("228.5")


SAMPLE_BARS_RESPONSE = {
    "candles": [
        {
            "datetime": 1715731200000,
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1_000_000,
            "vwap": 100.5,
        },
        {
            "datetime": 1715817600000,
            "open": 101.0,
            "high": 103.0,
            "low": 100.5,
            "close": 102.5,
            "volume": 1_100_000,
            "vwap": 101.5,
        },
    ],
    "symbol": "AAPL",
}


async def test_get_bars_maps_candles_to_bars() -> None:
    mock = AsyncMock()
    mock.get_price_history = AsyncMock(return_value=_make_response(200, SAMPLE_BARS_RESPONSE))
    client = _client_with(mock)
    bars = await client.get_bars("AAPL", timeframe="1d", limit=10)
    assert len(bars) == 2
    assert bars[0].open == Decimal("100.0")
    assert bars[0].close == Decimal("101.0")
    assert bars[0].volume == 1_000_000
    # 1d → vwap is None even when present in response
    assert bars[0].vwap is None


async def test_get_bars_intraday_keeps_vwap() -> None:
    mock = AsyncMock()
    mock.get_price_history = AsyncMock(return_value=_make_response(200, SAMPLE_BARS_RESPONSE))
    client = _client_with(mock)
    bars = await client.get_bars("AAPL", timeframe="5m", limit=10)
    assert bars[0].vwap == Decimal("100.5")


SAMPLE_CHAIN_RESPONSE = {
    "symbol": "AAPL",
    "underlying": {"last": 228.50},
    "callExpDateMap": {
        "2026-05-15:9": {
            "228.0": [
                {
                    "putCall": "CALL",
                    "symbol": "AAPL  260515C00228000",
                    "bid": 2.50,
                    "ask": 2.60,
                    "last": 2.55,
                    "totalVolume": 1500,
                    "openInterest": 8000,
                    "volatility": 28.5,
                    "delta": 0.52,
                    "gamma": 0.04,
                    "theta": -0.10,
                    "vega": 0.15,
                    "rho": 0.08,
                    "strikePrice": 228.0,
                    "expirationDate": 1715731200000,
                    "daysToExpiration": 9,
                }
            ],
        }
    },
    "putExpDateMap": {
        "2026-05-15:9": {
            "228.0": [
                {
                    "putCall": "PUT",
                    "symbol": "AAPL  260515P00228000",
                    "bid": 2.30,
                    "ask": 2.40,
                    "last": 2.35,
                    "totalVolume": 1100,
                    "openInterest": 6000,
                    "volatility": 30.5,
                    "delta": -0.48,
                    "gamma": 0.04,
                    "theta": -0.10,
                    "vega": 0.15,
                    "rho": -0.06,
                    "strikePrice": 228.0,
                    "expirationDate": 1715731200000,
                    "daysToExpiration": 9,
                }
            ],
        }
    },
}


async def test_get_options_chain_maps_calls_and_puts() -> None:
    mock = AsyncMock()
    mock.get_option_chain = AsyncMock(return_value=_make_response(200, SAMPLE_CHAIN_RESPONSE))
    client = _client_with(mock)

    chain = await client.get_options_chain("AAPL", contract_type="both")
    assert chain.underlying == "AAPL"
    assert chain.spot_at_fetch == Decimal("228.5")
    assert len(chain.calls_only()) == 1
    assert len(chain.puts_only()) == 1
    call = chain.calls_only()[0]
    assert call.strike == Decimal("228.0")
    # Schwab volatility is in % — confirm normalized to decimal
    assert call.iv == Decimal("0.285")
    assert call.delta == Decimal("0.52")
    assert call.symbol == "AAPL  260515C00228000".strip()


async def test_get_options_chain_filters_by_dte() -> None:
    mock = AsyncMock()
    mock.get_option_chain = AsyncMock(return_value=_make_response(200, SAMPLE_CHAIN_RESPONSE))
    client = _client_with(mock)
    chain = await client.get_options_chain("AAPL", min_dte=20)
    # Sample DTE is 9, so filtering excludes everything
    assert len(chain.contracts) == 0


SAMPLE_ACCOUNT_NUMBERS = [{"accountNumber": "123456789", "hashValue": "abc-hash"}]
SAMPLE_ACCOUNT_DETAIL = {
    "securitiesAccount": {
        "accountNumber": "123456789",
        "type": "CASH",
        "currentBalances": {
            "buyingPower": 100000,
            "cashBalance": 100000,
            "equity": 100000,
            "liquidationValue": 100000,
        },
        "positions": [],
        "roundTrips": 0,
        "isDayTrader": False,
    }
}


async def test_get_account_state_maps_balances() -> None:
    mock = AsyncMock()
    mock.get_account_numbers = AsyncMock(return_value=_make_response(200, SAMPLE_ACCOUNT_NUMBERS))
    mock.get_account = AsyncMock(return_value=_make_response(200, SAMPLE_ACCOUNT_DETAIL))
    client = _client_with(mock)

    state = await client.get_account_state()
    assert state.account_id == "123456789"
    assert state.buying_power == Decimal("100000")
    assert state.is_pdt is False
    assert state.margin_buying_power is None  # cash account
    assert state.pdt_count_remaining == 3


async def test_health_check_returns_false_on_error() -> None:
    mock = AsyncMock()
    mock.get_market_hours = AsyncMock(side_effect=Exception("boom"))
    client = _client_with(mock)
    assert await client.health_check() is False


async def test_constructor_without_creds_raises_auth_required() -> None:
    with pytest.raises(SchwabAuthRequired):
        SchwabDataClient()


async def test_constructor_with_missing_token_file_raises() -> None:
    with pytest.raises(SchwabAuthRequired, match="Schwab token not found"):
        SchwabDataClient(
            client_id="x",
            client_secret="y",
            redirect_uri="https://localhost",
            token_path="/nonexistent/token.json",
        )
