"""Phase 8.7: quick_check tool against the MockDataClient."""

from __future__ import annotations

import pytest

from services.mcp.tools.quick_check import (
    MAX_TICKERS_PER_CALL,
    quick_check,
)
from shared.clients.mock_market_data import MockDataClient


@pytest.fixture
def mock_client() -> MockDataClient:
    return MockDataClient(seed=42)


async def test_single_ticker_returns_flat_dict(mock_client: MockDataClient) -> None:
    result = await quick_check("SPY", mock_client)
    assert "ticker" in result
    assert result["ticker"] == "SPY"
    assert "price" in result
    assert "rsi_14" in result
    assert "summary" in result


async def test_multiple_tickers_returns_dict_of_dicts(
    mock_client: MockDataClient,
) -> None:
    result = await quick_check(["SPY", "NVDA"], mock_client)
    assert set(result.keys()) == {"SPY", "NVDA"}
    assert "rsi_14" in result["SPY"]
    assert "rsi_14" in result["NVDA"]


async def test_tickers_uppercase_keyed(mock_client: MockDataClient) -> None:
    result = await quick_check(["spy", "nvda"], mock_client)
    assert "SPY" in result
    assert "NVDA" in result


async def test_too_many_tickers_raises(mock_client: MockDataClient) -> None:
    with pytest.raises(ValueError, match="Maximum"):
        await quick_check(
            ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K"], mock_client
        )
    assert MAX_TICKERS_PER_CALL == 10


async def test_empty_list_raises(mock_client: MockDataClient) -> None:
    with pytest.raises(ValueError, match="empty"):
        await quick_check([], mock_client)


async def test_error_per_ticker_isolated(mock_client: MockDataClient) -> None:
    """One bad ticker should not poison the whole batch."""

    class _PartialFailure(MockDataClient):
        async def get_bars(self, ticker: str, *args: object, **kwargs: object) -> object:  # type: ignore[override]
            if ticker == "BAD":
                raise RuntimeError("synthetic failure for BAD")
            return await super().get_bars(ticker, *args, **kwargs)  # type: ignore[arg-type]

    client = _PartialFailure(seed=42)
    result = await quick_check(["SPY", "BAD", "NVDA"], client)
    assert "error" in result["BAD"]
    assert "synthetic failure for BAD" in result["BAD"]["error"]
    # Others still computed normally
    assert "rsi_14" in result["SPY"]
    assert "rsi_14" in result["NVDA"]
