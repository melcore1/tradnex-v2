"""Trend indicator tests: EMA, SMA, ADX, crossover detection."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
import ta

from shared.analytics import (
    InsufficientBarsError,
    above_200_sma,
    detect_crossover,
)
from shared.analytics import (
    adx as adx_func,
)
from shared.analytics import (
    ema as ema_func,
)
from shared.analytics import (
    sma as sma_func,
)
from shared.schemas.market import Bar


def _make_bars(closes, *, seed: int = 1) -> list[Bar]:
    rng = np.random.default_rng(seed)
    closes_list = list(closes)
    bars: list[Bar] = []
    for i, close in enumerate(closes_list):
        prev_close = closes_list[i - 1] if i > 0 else float(close)
        open_p = float(prev_close) + float(rng.normal(0.0, 0.1))
        high = max(open_p, float(close)) + abs(float(rng.normal(0.0, 0.2)))
        low = min(open_p, float(close)) - abs(float(rng.normal(0.0, 0.2)))
        bars.append(
            Bar(
                timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i),
                open=Decimal(str(round(open_p, 4))),
                high=Decimal(str(round(high, 4))),
                low=Decimal(str(round(low, 4))),
                close=Decimal(str(round(float(close), 4))),
                volume=1_000_000,
            )
        )
    return bars


def _walk(n: int, seed: int = 42, start: float = 100.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return start + np.cumsum(rng.normal(0.0, 1.0, n))


def test_sma_simple_known_values() -> None:
    bars = _make_bars([10, 20, 30, 40, 50])
    result = sma_func(bars, period=3)
    # SMA(3): (10+20+30)/3 = 20, (20+30+40)/3 = 30, (30+40+50)/3 = 40
    assert result.series == [Decimal("20"), Decimal("30"), Decimal("40")]
    assert result.latest == Decimal("40")


def test_sma_matches_ta_library() -> None:
    closes = _walk(50)
    bars = _make_bars(closes)
    our = sma_func(bars, period=20)
    expected = float(
        ta.trend.SMAIndicator(pd.Series(closes), window=20).sma_indicator().dropna().iloc[-1]
    )
    assert abs(float(our.latest) - expected) < 0.01


def test_sma_insufficient_bars() -> None:
    with pytest.raises(InsufficientBarsError):
        sma_func(_make_bars([1, 2, 3]), period=10)


def test_ema_matches_ta_library() -> None:
    closes = _walk(60)
    bars = _make_bars(closes)
    our = ema_func(bars, period=12)
    expected = float(
        ta.trend.EMAIndicator(pd.Series(closes), window=12).ema_indicator().dropna().iloc[-1]
    )
    # ta uses Wilder's bootstrap which can differ slightly; loose tolerance
    assert abs(float(our.latest) - expected) < 1.0


def test_ema_on_flat_data_equals_value() -> None:
    bars = _make_bars([50.0] * 30)
    result = ema_func(bars, period=10)
    assert abs(float(result.latest) - 50.0) < 0.01


def test_adx_matches_ta_library_within_tolerance() -> None:
    rng = np.random.default_rng(1)
    n = 100
    closes = 100 + np.cumsum(rng.normal(0.0, 1.0, n))
    bars = _make_bars(closes, seed=1)
    df = pd.DataFrame(
        {
            "high": [float(b.high) for b in bars],
            "low": [float(b.low) for b in bars],
            "close": [float(b.close) for b in bars],
        }
    )
    our = adx_func(bars, period=14)
    expected_adx = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
    expected_latest = float(expected_adx.adx().dropna().iloc[-1])
    # ADX implementations vary slightly in bootstrap; loose tolerance
    assert abs(float(our.latest_adx) - expected_latest) < 5.0


def test_adx_strong_uptrend_classification() -> None:
    closes = list(np.linspace(100, 200, 60))
    bars = _make_bars(closes)
    result = adx_func(bars, period=14)
    # Linear uptrend → +DI dominates → bullish direction
    assert result.direction == "bullish"


def test_adx_insufficient_bars() -> None:
    with pytest.raises(InsufficientBarsError):
        adx_func(_make_bars(_walk(20)), period=14)  # need 28


def test_detect_crossover_above() -> None:
    fast = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]
    slow = [Decimal("3"), Decimal("3"), Decimal("3"), Decimal("3")]
    assert detect_crossover(fast, slow, lookback=3) == "crossed_above"


def test_detect_crossover_below() -> None:
    fast = [Decimal("4"), Decimal("3"), Decimal("2"), Decimal("1")]
    slow = [Decimal("3"), Decimal("3"), Decimal("3"), Decimal("3")]
    assert detect_crossover(fast, slow, lookback=3) == "crossed_below"


def test_detect_crossover_none() -> None:
    fast = [Decimal("4"), Decimal("4"), Decimal("4"), Decimal("4")]
    slow = [Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1")]
    assert detect_crossover(fast, slow, lookback=3) == "none"


def test_above_200_sma_true_when_price_above() -> None:
    # Build 200 bars where price is rising — last close above SMA200
    closes = list(np.linspace(100, 200, 220))
    bars = _make_bars(closes)
    assert above_200_sma(bars) is True


def test_above_200_sma_insufficient_bars() -> None:
    bars = _make_bars(_walk(150))
    with pytest.raises(InsufficientBarsError):
        above_200_sma(bars)
