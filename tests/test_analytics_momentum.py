"""Momentum indicator tests: RSI, MACD.

Cross-validates against the `ta` library (pure-Python TA, no C deps) where
applicable; hand-calculated cases pin down corner behavior.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
import ta

from shared.analytics import (
    InsufficientBarsError,
)
from shared.analytics import (
    macd as macd_func,
)
from shared.analytics import (
    rsi as rsi_func,
)
from shared.schemas.market import Bar


def _make_bars(closes: list[float] | np.ndarray, *, ohlc_jitter_seed: int = 1) -> list[Bar]:
    rng = np.random.default_rng(ohlc_jitter_seed)
    bars: list[Bar] = []
    closes_list = list(closes)
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


def _seeded_random_walk(n: int, seed: int = 42, start: float = 100.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return start + np.cumsum(rng.normal(0.0, 1.0, n))


def test_rsi_matches_ta_library() -> None:
    closes = _seeded_random_walk(100)
    bars = _make_bars(closes)

    our = rsi_func(bars, period=14)
    expected = ta.momentum.RSIIndicator(pd.Series(closes), window=14).rsi()
    expected_latest = float(expected.dropna().iloc[-1])
    assert abs(float(our.latest) - expected_latest) < 0.01


def test_rsi_monotonic_rising_returns_high_value() -> None:
    closes = list(range(100, 130))  # strictly rising
    bars = _make_bars(closes)
    result = rsi_func(bars, period=14)
    # All gains, no losses → RSI should be at or near 100
    assert result.latest > Decimal("99")


def test_rsi_monotonic_falling_returns_low_value() -> None:
    closes = list(range(130, 100, -1))  # strictly falling
    bars = _make_bars(closes)
    result = rsi_func(bars, period=14)
    assert result.latest < Decimal("1")


def test_rsi_insufficient_bars_raises() -> None:
    bars = _make_bars(list(range(100, 110)))  # 10 bars, period 14 needs 15
    with pytest.raises(InsufficientBarsError) as exc:
        rsi_func(bars, period=14)
    assert exc.value.required == 15
    assert exc.value.got == 10


def test_rsi_regime_classification() -> None:
    # 30 bars all gains → RSI 100 → overbought
    bars = _make_bars(list(range(100, 130)))
    result = rsi_func(bars, period=14)
    assert result.regime == "overbought"


def test_rsi_series_length_aligns_with_bars() -> None:
    closes = _seeded_random_walk(50)
    bars = _make_bars(closes)
    result = rsi_func(bars, period=14)
    # series length = len(deltas) - period + 1 = (50 - 1) - 14 + 1 = 36
    assert len(result.series) == 36


def test_macd_matches_ta_library() -> None:
    closes = _seeded_random_walk(120)
    bars = _make_bars(closes)
    our = macd_func(bars)

    macd_ind = ta.trend.MACD(pd.Series(closes), window_slow=26, window_fast=12, window_sign=9)
    expected_line = float(macd_ind.macd().dropna().iloc[-1])
    expected_signal = float(macd_ind.macd_signal().dropna().iloc[-1])
    expected_hist = float(macd_ind.macd_diff().dropna().iloc[-1])

    assert abs(float(our.latest_line) - expected_line) < 0.05
    assert abs(float(our.latest_signal) - expected_signal) < 0.05
    assert abs(float(our.latest_histogram) - expected_hist) < 0.05


def test_macd_insufficient_bars_raises() -> None:
    bars = _make_bars(_seeded_random_walk(30))  # need 35 minimum (slow + signal)
    with pytest.raises(InsufficientBarsError):
        macd_func(bars)


def test_macd_line_above_signal_in_recent_breakout() -> None:
    # Long flat base, then sudden uptrend in the most recent bars. Fast EMA reacts
    # quicker than slow; line should be above signal during the breakout.
    closes = list(np.concatenate([np.full(70, 100.0), np.linspace(100, 130, 30)]))
    bars = _make_bars(closes)
    result = macd_func(bars)
    assert result.line_above_signal is True


def test_macd_histogram_trend_returns_valid_state() -> None:
    bars = _make_bars(_seeded_random_walk(100))
    result = macd_func(bars)
    assert result.histogram_trend in ("increasing", "decreasing", "flat")


def test_macd_series_lengths_aligned() -> None:
    closes = _seeded_random_walk(100)
    bars = _make_bars(closes)
    result = macd_func(bars)
    assert (
        len(result.series_line)
        == len(result.series_signal)
        == len(result.series_histogram)
    )
