"""Integration tests for compute_full_analysis()."""


import pytest

from shared.analytics import compute_full_analysis
from shared.clients.mock_market_data import MockDataClient


@pytest.fixture
async def nvda_bars():
    client = MockDataClient(seed=42)
    return await client.get_bars("NVDA", timeframe="1d", limit=300)


async def test_full_analysis_populates_every_field(nvda_bars) -> None:
    fa = await compute_full_analysis("NVDA", nvda_bars, timeframe="1d")
    assert fa.ticker == "NVDA"
    assert fa.bars_count == 300
    assert fa.timeframe == "1d"
    assert fa.spot > 0
    # Required indicators
    assert fa.rsi.latest is not None
    assert fa.macd.latest_line is not None
    assert fa.ema9.latest is not None
    assert fa.ema21.latest is not None
    assert fa.sma50.latest is not None
    assert fa.sma200 is not None
    assert fa.adx.latest_adx is not None
    assert fa.atr.latest is not None
    assert fa.bollinger.latest_middle is not None
    assert fa.fibonacci.swing_high is not None
    # GARCH/MC may None-out if fit fails; on 300 bars it should succeed
    assert fa.garch is not None
    assert fa.monte_carlo is not None


async def test_full_analysis_summary_mentions_ticker(nvda_bars) -> None:
    fa = await compute_full_analysis("NVDA", nvda_bars)
    assert "NVDA" in fa.summary


async def test_full_analysis_serializes_to_json(nvda_bars) -> None:
    fa = await compute_full_analysis("NVDA", nvda_bars)
    data = fa.model_dump_json()
    assert "NVDA" in data
    assert "rsi" in data
    assert "macd" in data
    assert "garch" in data


async def test_full_analysis_vwap_is_none_for_daily(nvda_bars) -> None:
    fa = await compute_full_analysis("NVDA", nvda_bars, timeframe="1d")
    assert fa.vwap is None


async def test_full_analysis_vwap_present_for_intraday() -> None:
    client = MockDataClient(seed=42)
    bars = await client.get_bars("NVDA", timeframe="5m", limit=300)
    fa = await compute_full_analysis("NVDA", bars, timeframe="5m")
    assert fa.vwap is not None
    assert fa.vwap.latest > 0


async def test_full_analysis_handles_empty_bars() -> None:
    with pytest.raises(ValueError):
        await compute_full_analysis("NVDA", [])


async def test_full_analysis_crossover_is_valid_state(nvda_bars) -> None:
    fa = await compute_full_analysis("NVDA", nvda_bars)
    assert fa.ema9_21_crossover in ("crossed_above", "crossed_below", "none")
    assert fa.sma50_200_crossover in ("crossed_above", "crossed_below", "none")


async def test_full_analysis_spot_override_used_in_summary(nvda_bars) -> None:
    """Regression for the live diagnostic: quick_check showed `price: 430.31`
    (live quote) but `summary: "TSLA at 433.443"` because the summary's spot
    was bars[-1].close (lagging the live quote). With `spot_override`,
    callers can pass the live quote and the summary stays consistent."""
    from decimal import Decimal as _Decimal

    fa = await compute_full_analysis(
        "NVDA", nvda_bars, spot_override=_Decimal("999.99")
    )
    assert fa.spot == _Decimal("999.99")
    assert "999.99" in fa.summary


async def test_full_analysis_above_200_sma_is_none_when_bars_insufficient() -> None:
    """Regression: scout NVDA with days_history=90 returned sma200:null but
    above_200_sma:false. Downstream the 6-rule strategy's H1 silently failed
    on every <200-bar ticker. The flag must be tri-state — None when
    insufficient bars, distinguishable from "price below 200-SMA"."""
    client = MockDataClient(seed=42)
    bars = await client.get_bars("NVDA", timeframe="1d", limit=90)
    fa = await compute_full_analysis("NVDA", bars, timeframe="1d")
    assert fa.sma200 is None
    assert fa.above_200_sma is None, (
        f"above_200_sma must be None when sma200 is None, got {fa.above_200_sma!r}"
    )
