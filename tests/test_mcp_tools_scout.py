"""Phase 8.7: scout tool — full Tier 2 + Tier 3 + regime."""

from __future__ import annotations

import pytest

from services.mcp.tools.scout import scout
from shared.clients.mock_market_data import MockDataClient
from tests._api_helpers import reset_modules_for_test_db
from tests._credential_helpers import TEST_ENCRYPTION_KEY


@pytest.fixture
def db_with_env(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    return reset_modules_for_test_db(tmp_path, monkeypatch)


@pytest.fixture
def mock_client() -> MockDataClient:
    return MockDataClient(seed=42)


async def test_single_ticker_returns_full_block(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    result = await scout("SPY", days_history=250, client=mock_client)
    assert result["ticker"] == "SPY"
    assert "tier2" in result
    assert "tier3_options" in result
    assert "tier4_regime" in result
    assert "summary" in result
    assert "rsi" in result["tier2"]
    assert "gex" in result["tier3_options"]
    assert "overall" in result["tier4_regime"]


async def test_multi_ticker_returns_dict(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    result = await scout(["SPY", "NVDA"], days_history=250, client=mock_client)
    assert set(result.keys()) == {"SPY", "NVDA"}


async def test_too_many_tickers_raises(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    with pytest.raises(ValueError, match="Maximum"):
        await scout(["A"] * 11, days_history=250, client=mock_client)


async def test_days_history_out_of_range_raises(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    with pytest.raises(ValueError, match="between"):
        await scout("SPY", days_history=10, client=mock_client)
    with pytest.raises(ValueError, match="between"):
        await scout("SPY", days_history=10_000, client=mock_client)


async def test_options_block_included_when_chain_present(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    result = await scout("NVDA", days_history=250, client=mock_client)
    options = result["tier3_options"]
    assert options is not None
    assert "gex" in options
    assert "iv_rank" in options


async def test_tier4_regime_block_uses_atr_regime_key(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    """Regression: the regime sub-field was `volatility` but read as
    contradictory next to a composite `overall` label that uses
    Bollinger-squeeze semantics. Renamed to `atr_regime` so the field's
    actual source (ATR) is explicit. Old `volatility` key must not appear."""
    result = await scout("SPY", days_history=250, client=mock_client)
    regime = result["tier4_regime"]
    assert "atr_regime" in regime
    assert "volatility" not in regime
    # The composite `overall` field must still be present.
    assert "overall" in regime
