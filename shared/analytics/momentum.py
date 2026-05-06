"""Momentum indicators: RSI, MACD."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import numpy as np
from pydantic import computed_field

from shared.analytics.base import (
    IndicatorResult,
    InsufficientBarsError,
    closes_array,
    decimal_series,
    ema_array,
    to_decimal,
)
from shared.schemas.market import Bar


class RSIResult(IndicatorResult):
    latest: Decimal
    series: list[Decimal]
    period: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def trend(self) -> Literal["rising", "falling", "flat"]:
        if len(self.series) < 4:
            return "flat"
        recent = self.series[-1]
        prior = self.series[-4]
        if prior == 0:
            return "flat"
        diff_pct = (recent - prior) / prior * Decimal("100")
        if diff_pct > Decimal("1"):
            return "rising"
        if diff_pct < Decimal("-1"):
            return "falling"
        return "flat"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def regime(self) -> Literal["oversold", "neutral", "overbought"]:
        if self.latest < Decimal("30"):
            return "oversold"
        if self.latest > Decimal("70"):
            return "overbought"
        return "neutral"


def rsi(bars: list[Bar], period: int = 14) -> RSIResult:
    """Wilder's RSI over closes."""
    if len(bars) < period + 1:
        raise InsufficientBarsError(required=period + 1, got=len(bars))

    closes = closes_array(bars)
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    n = len(deltas)
    avg_gain = np.zeros(n)
    avg_loss = np.zeros(n)
    avg_gain[period - 1] = gains[:period].mean()
    avg_loss[period - 1] = losses[:period].mean()
    for i in range(period, n):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i]) / period

    rs = np.divide(
        avg_gain,
        avg_loss,
        out=np.full_like(avg_gain, np.inf),
        where=avg_loss != 0,
    )
    rsi_values = 100.0 - 100.0 / (1.0 + rs)
    rsi_values[avg_loss == 0] = 100.0  # all gains → RSI 100

    valid = rsi_values[period - 1 :]

    return RSIResult(
        timestamp=datetime.now(UTC),
        bars_used=len(bars),
        latest=to_decimal(float(valid[-1])),
        series=decimal_series(valid),
        period=period,
    )


class MACDResult(IndicatorResult):
    latest_line: Decimal
    latest_signal: Decimal
    latest_histogram: Decimal
    series_line: list[Decimal]
    series_signal: list[Decimal]
    series_histogram: list[Decimal]
    fast: int
    slow: int
    signal: int
    bullish_divergence_at_pullback_low: bool

    @computed_field  # type: ignore[prop-decorator]
    @property
    def histogram_trend(self) -> Literal["increasing", "decreasing", "flat"]:
        if len(self.series_histogram) < 4:
            return "flat"
        recent = self.series_histogram[-1]
        prior = self.series_histogram[-4]
        diff = recent - prior
        if abs(diff) < Decimal("0.01"):
            return "flat"
        return "increasing" if diff > 0 else "decreasing"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def line_above_signal(self) -> bool:
        return self.latest_line > self.latest_signal

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recently_crossed_above(self) -> bool:
        return _recent_cross(self.series_line, self.series_signal, direction="above")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recently_crossed_below(self) -> bool:
        return _recent_cross(self.series_line, self.series_signal, direction="below")


def _recent_cross(
    fast_series: list[Decimal],
    slow_series: list[Decimal],
    *,
    direction: Literal["above", "below"],
    lookback: int = 3,
) -> bool:
    if len(fast_series) < 2 or len(slow_series) < 2:
        return False
    n = min(len(fast_series), len(slow_series))
    start = max(1, n - lookback)
    for i in range(start, n):
        prev_fast, prev_slow = fast_series[i - 1], slow_series[i - 1]
        curr_fast, curr_slow = fast_series[i], slow_series[i]
        if direction == "above" and prev_fast <= prev_slow and curr_fast > curr_slow:
            return True
        if direction == "below" and prev_fast >= prev_slow and curr_fast < curr_slow:
            return True
    return False


def _detect_bullish_divergence(
    closes: np.ndarray,
    histogram: np.ndarray,
    *,
    lookback: int,
) -> bool:
    """Return True when price made a lower low but histogram made a higher low."""
    if len(closes) < lookback + 2:
        return False
    window = closes[-lookback:]
    hist_window = histogram[-lookback:]
    minima = []
    for i in range(1, len(window) - 1):
        if window[i] < window[i - 1] and window[i] < window[i + 1]:
            minima.append(i)
    if len(minima) < 2:
        return False
    last, prev = minima[-1], minima[-2]
    return bool(window[last] < window[prev] and hist_window[last] > hist_window[prev])


def macd(
    bars: list[Bar],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    divergence_lookback: int = 20,
) -> MACDResult:
    if len(bars) < slow + signal:
        raise InsufficientBarsError(required=slow + signal, got=len(bars))

    closes = closes_array(bars)
    fast_ema = ema_array(closes, fast)
    slow_ema = ema_array(closes, slow)
    macd_line = fast_ema - slow_ema  # valid from slow-1

    macd_valid_start = slow - 1
    macd_valid = macd_line[macd_valid_start:]
    signal_valid = ema_array(macd_valid, signal)
    signal_full = np.zeros(len(closes))
    signal_full[macd_valid_start:] = signal_valid
    histogram = macd_line - signal_full

    valid_start = slow + signal - 2

    return MACDResult(
        timestamp=datetime.now(UTC),
        bars_used=len(bars),
        latest_line=to_decimal(float(macd_line[-1])),
        latest_signal=to_decimal(float(signal_full[-1])),
        latest_histogram=to_decimal(float(histogram[-1])),
        series_line=decimal_series(macd_line[valid_start:]),
        series_signal=decimal_series(signal_full[valid_start:]),
        series_histogram=decimal_series(histogram[valid_start:]),
        fast=fast,
        slow=slow,
        signal=signal,
        bullish_divergence_at_pullback_low=_detect_bullish_divergence(
            closes, histogram, lookback=divergence_lookback
        ),
    )
