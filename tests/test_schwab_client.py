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


async def test_get_bars_daily_passes_year_period_type() -> None:
    """Regression: Schwab rejects period_type=day + frequency_type=daily as 400.

    Daily bars must pass period_type=year + frequency_type=daily.
    """
    mock = AsyncMock()
    mock.get_price_history = AsyncMock(return_value=_make_response(200, SAMPLE_BARS_RESPONSE))
    client = _client_with(mock)
    await client.get_bars("AAPL", timeframe="1d", limit=10)
    call_kwargs = mock.get_price_history.call_args.kwargs
    assert call_kwargs["period_type"] == "year"
    assert call_kwargs["frequency_type"] == "daily"


async def test_get_bars_minute_passes_day_period_type() -> None:
    """Regression: Minute bars must pass period_type=day + frequency_type=minute."""
    mock = AsyncMock()
    mock.get_price_history = AsyncMock(return_value=_make_response(200, SAMPLE_BARS_RESPONSE))
    client = _client_with(mock)
    await client.get_bars("AAPL", timeframe="5m", limit=10)
    call_kwargs = mock.get_price_history.call_args.kwargs
    assert call_kwargs["period_type"] == "day"
    assert call_kwargs["frequency_type"] == "minute"
    assert call_kwargs["frequency"] == 5


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


async def test_get_options_chain_handles_iso_expiration_date() -> None:
    """Regression: Schwab Trader API returns ``expirationDate`` as an ISO-format
    string (e.g. ``"2026-05-19T20:00:00.000+00:00"``), NOT as int millis-epoch.

    The pre-fix code did ``exp_ms / 1000`` which raised
    ``TypeError: unsupported operand type(s) for /: 'str' and 'int'``.
    """
    iso_response = {
        **SAMPLE_CHAIN_RESPONSE,
        "callExpDateMap": {
            "2026-05-15:9": {
                "228.0": [
                    {
                        **SAMPLE_CHAIN_RESPONSE["callExpDateMap"]["2026-05-15:9"]["228.0"][0],
                        "expirationDate": "2026-05-15T20:00:00.000+00:00",
                    }
                ],
            }
        },
        "putExpDateMap": {
            "2026-05-15:9": {
                "228.0": [
                    {
                        **SAMPLE_CHAIN_RESPONSE["putExpDateMap"]["2026-05-15:9"]["228.0"][0],
                        "expirationDate": "2026-05-15T20:00:00.000+00:00",
                    }
                ],
            }
        },
    }
    mock = AsyncMock()
    mock.get_option_chain = AsyncMock(return_value=_make_response(200, iso_response))
    client = _client_with(mock)
    chain = await client.get_options_chain("AAPL", contract_type="both")
    assert len(chain.calls_only()) == 1
    assert chain.calls_only()[0].expiration.isoformat() == "2026-05-15"


async def test_get_options_chain_handles_date_only_expiration_string() -> None:
    """Schwab sometimes returns a date-only string like "2026-05-15"."""
    date_only = {
        **SAMPLE_CHAIN_RESPONSE,
        "callExpDateMap": {
            "2026-05-15:9": {
                "228.0": [
                    {
                        **SAMPLE_CHAIN_RESPONSE["callExpDateMap"]["2026-05-15:9"]["228.0"][0],
                        "expirationDate": "2026-05-15",
                    }
                ],
            }
        },
        "putExpDateMap": {},
    }
    mock = AsyncMock()
    mock.get_option_chain = AsyncMock(return_value=_make_response(200, date_only))
    client = _client_with(mock)
    chain = await client.get_options_chain("AAPL", contract_type="call")
    assert chain.calls_only()[0].expiration.isoformat() == "2026-05-15"


async def test_get_options_chain_handles_null_days_to_expiration() -> None:
    """Regression: when the chain row has ``daysToExpiration: null`` (e.g.
    early-bird non-standard contracts), ``int(None)`` raises ``TypeError``."""
    null_dte = {
        **SAMPLE_CHAIN_RESPONSE,
        "callExpDateMap": {
            "2026-05-15:9": {
                "228.0": [
                    {
                        **SAMPLE_CHAIN_RESPONSE["callExpDateMap"]["2026-05-15:9"]["228.0"][0],
                        "daysToExpiration": None,
                    }
                ],
            }
        },
        "putExpDateMap": {},
    }
    mock = AsyncMock()
    mock.get_option_chain = AsyncMock(return_value=_make_response(200, null_dte))
    client = _client_with(mock)
    chain = await client.get_options_chain("AAPL", contract_type="call")
    assert chain.calls_only()[0].dte == 0


async def test_get_options_chain_handles_null_underlying() -> None:
    """Regression: Schwab returns ``"underlying": null`` (not missing) in some
    responses (e.g. mid-after-hours, low-volume names). ``data.get(key, {})``
    only kicks in for missing keys — explicit None values bypass the default
    and cause ``AttributeError: 'NoneType' object has no attribute 'get'``.
    """
    mock = AsyncMock()
    response_with_null = {**SAMPLE_CHAIN_RESPONSE, "underlying": None}
    mock.get_option_chain = AsyncMock(return_value=_make_response(200, response_with_null))
    client = _client_with(mock)
    chain = await client.get_options_chain("AAPL", contract_type="both")
    assert chain.underlying == "AAPL"
    assert chain.spot_at_fetch == Decimal("0")  # falls back to 0 when underlying missing
    assert len(chain.calls_only()) == 1


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


async def test_get_account_state_handles_null_round_trips() -> None:
    """Regression: ``roundTrips`` is occasionally null in real responses; the
    pre-fix ``int(None)`` would raise ``TypeError``."""
    detail = {
        "securitiesAccount": {
            **SAMPLE_ACCOUNT_DETAIL["securitiesAccount"],
            "roundTrips": None,
        }
    }
    mock = AsyncMock()
    mock.get_account_numbers = AsyncMock(return_value=_make_response(200, SAMPLE_ACCOUNT_NUMBERS))
    mock.get_account = AsyncMock(return_value=_make_response(200, detail))
    client = _client_with(mock)
    state = await client.get_account_state()
    assert state.pdt_count_remaining == 3


SAMPLE_MOVERS_RESPONSE_VOLUME = {
    "screeners": [
        {
            "symbol": "NVDA",
            "description": "NVIDIA Corp",
            "lastPrice": 950.25,
            "netChange": 12.50,
            "netPercentChange": 1.33,
            "volume": 75_000_000,
            "totalVolume": 3_277_188_666,  # index aggregate, broadcast across rows
            "direction": "up",
            "trades": 500_000,
            "marketShare": 0.022,
        },
        {
            "symbol": "AAPL",
            "description": "Apple Inc",
            "lastPrice": 230.10,
            "netChange": -1.20,
            "netPercentChange": -0.52,
            "volume": 50_000_000,
            "totalVolume": 3_277_188_666,
            "direction": "down",
            "trades": 350_000,
            "marketShare": 0.015,
        },
    ]
}

SAMPLE_MOVERS_RESPONSE_GAINERS = {
    "screeners": [
        {
            "symbol": "SMCI",
            "description": "Super Micro",
            "lastPrice": 800.00,
            "netPercentChange": 8.50,
            "volume": 20_000_000,
            "totalVolume": 3_277_188_666,
        },
    ]
}

SAMPLE_MOVERS_RESPONSE_LOSERS = {
    "screeners": [
        {
            "symbol": "INTC",
            "description": "Intel Corp",
            "lastPrice": 22.10,
            "netPercentChange": -5.30,
            "volume": 80_000_000,
            "totalVolume": 3_277_188_666,
        },
    ]
}


async def test_get_movers_invokes_three_distinct_sort_orders() -> None:
    """Regression: each of the three mover categories MUST invoke the
    underlying Schwab API with a distinct ``sort_order`` argument. Earlier
    production data showed identical lists across most_active / gainers /
    losers, which would surface here as repeated kwargs."""

    def _per_sort(*args: Any, **kwargs: Any) -> Any:
        so = kwargs.get("sort_order")
        if so == "PERCENT_CHANGE_UP":
            return _make_response(200, SAMPLE_MOVERS_RESPONSE_GAINERS)
        if so == "PERCENT_CHANGE_DOWN":
            return _make_response(200, SAMPLE_MOVERS_RESPONSE_LOSERS)
        return _make_response(200, SAMPLE_MOVERS_RESPONSE_VOLUME)

    mock = AsyncMock()
    mock.get_movers = AsyncMock(side_effect=_per_sort)
    client = _client_with(mock)

    movers = await client.get_movers()

    # Three calls, one per category, with three distinct sort_order values.
    assert mock.get_movers.call_count == 3
    sort_orders_passed = [
        call.kwargs.get("sort_order") for call in mock.get_movers.call_args_list
    ]
    assert set(sort_orders_passed) == {
        "VOLUME",
        "PERCENT_CHANGE_UP",
        "PERCENT_CHANGE_DOWN",
    }, f"Each category must use a distinct sort_order, got {sort_orders_passed}"

    # And each call should hit the $SPX index with frequency=10.
    for call in mock.get_movers.call_args_list:
        assert call.args == ("$SPX",)
        assert call.kwargs.get("frequency") == 10

    # The categories should map to disjoint ticker sets given disjoint responses.
    assert {m.ticker for m in movers.most_active} == {"NVDA", "AAPL"}
    assert {m.ticker for m in movers.top_gainers} == {"SMCI"}
    assert {m.ticker for m in movers.top_losers} == {"INTC"}


async def test_get_movers_uses_per_symbol_volume_not_index_aggregate() -> None:
    """Regression: Schwab Screener rows include both ``volume`` (per-symbol)
    and ``totalVolume`` (index aggregate broadcast to every row). Reading
    ``totalVolume`` made every mover show the same ~3.3B value in production
    output. The mapping must use ``volume``.
    """
    mock = AsyncMock()
    mock.get_movers = AsyncMock(
        return_value=_make_response(200, SAMPLE_MOVERS_RESPONSE_VOLUME)
    )
    client = _client_with(mock)
    movers = await client.get_movers()

    # most_active was populated from SAMPLE_MOVERS_RESPONSE_VOLUME — two rows
    # with distinct per-symbol volumes; the index aggregate (3_277_188_666)
    # must not leak in anywhere.
    volumes = {m.volume for m in movers.most_active}
    assert 3_277_188_666 not in volumes
    assert volumes == {75_000_000, 50_000_000}

    by_ticker = {m.ticker: m for m in movers.most_active}
    assert by_ticker["NVDA"].last == Decimal("950.25")
    assert by_ticker["NVDA"].change_pct == Decimal("1.33")
    assert by_ticker["NVDA"].volume == 75_000_000
    assert by_ticker["AAPL"].volume == 50_000_000


async def test_get_movers_handles_malformed_rows() -> None:
    """Defensive: a row missing fields shouldn't crash the whole mapping.
    Each missing field falls back to a sensible zero/empty default and the
    surviving rows still come through."""
    malformed = {
        "screeners": [
            {},  # totally empty row
            {"symbol": "GOOG"},  # only ticker
            {
                "symbol": None,  # explicit null symbol
                "lastPrice": None,
                "netPercentChange": None,
                "volume": None,
            },
            {  # well-formed row mixed in
                "symbol": "msft",  # lowercase — should uppercase
                "lastPrice": 410.50,
                "netPercentChange": 0.75,
                "volume": 18_000_000,
            },
        ]
    }
    mock = AsyncMock()
    mock.get_movers = AsyncMock(return_value=_make_response(200, malformed))
    client = _client_with(mock)
    movers = await client.get_movers()

    # All four rows mapped without raising; defaults fill the blanks.
    assert len(movers.most_active) == 4
    by_index = movers.most_active
    assert by_index[0].ticker == ""
    assert by_index[0].last == Decimal("0")
    assert by_index[0].volume == 0
    assert by_index[1].ticker == "GOOG"
    assert by_index[2].ticker == ""  # None symbol → empty string
    assert by_index[2].volume == 0
    assert by_index[3].ticker == "MSFT"
    assert by_index[3].last == Decimal("410.5")
    assert by_index[3].volume == 18_000_000


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
