"""Trend indicators: EMA, SMA, ADX, crossover detection."""

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
    highs_array,
    lows_array,
    to_decimal,
    true_range,
)
from shared.schemas.market import Bar

CrossoverState = Literal["crossed_above", "crossed_below", "none"]


class EMAResult(IndicatorResult):
    latest: Decimal
    series: list[Decimal]
    period: int


class SMAResult(IndicatorResult):
    latest: Decimal
    series: list[Decimal]
    period: int


class ADXResult(IndicatorResult):
    latest_adx: Decimal
    latest_plus_di: Decimal
    latest_minus_di: Decimal
    series_adx: list[Decimal]
    series_plus_di: list[Decimal]
    series_minus_di: list[Decimal]
    period: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def trend_strength(self) -> Literal["weak", "moderate", "strong"]:
        if self.latest_adx < Decimal("20"):
            return "weak"
        if self.latest_adx < Decimal("40"):
            return "moderate"
        return "strong"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def direction(self) -> Literal["bullish", "bearish", "neutral"]:
        if self.latest_plus_di > self.latest_minus_di:
            return "bullish"
        if self.latest_minus_di > self.latest_plus_di:
            return "bearish"
        return "neutral"


def ema(bars: list[Bar], period: int) -> EMAResult:
    if len(bars) < period:
        raise InsufficientBarsError(required=period, got=len(bars))
    closes = closes_array(bars)
    ema_values = ema_array(closes, period)
    valid = ema_values[period - 1 :]
    return EMAResult(
        timestamp=datetime.now(UTC),
        bars_used=len(bars),
        latest=to_decimal(float(valid[-1])),
        series=decimal_series(valid),
        period=period,
    )


def sma(bars: list[Bar], period: int) -> SMAResult:
    if len(bars) < period:
        raise InsufficientBarsError(required=period, got=len(bars))
    closes = closes_array(bars)
    sma_values = np.convolve(closes, np.ones(period) / period, mode="valid")
    return SMAResult(
        timestamp=datetime.now(UTC),
        bars_used=len(bars),
        latest=to_decimal(float(sma_values[-1])),
        series=decimal_series(sma_values),
        period=period,
    )


def adx(bars: list[Bar], period: int = 14) -> ADXResult:
    if len(bars) < period * 2:
        raise InsufficientBarsError(required=period * 2, got=len(bars))

    highs = highs_array(bars)
    lows = lows_array(bars)
    closes = closes_array(bars)

    up_move = np.diff(highs)
    down_move = -np.diff(lows)
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = true_range(highs, lows, closes)[1:]  # align with diff length

    n = len(tr)
    smoothed_tr = np.zeros(n)
    smoothed_plus_dm = np.zeros(n)
    smoothed_minus_dm = np.zeros(n)

    smoothed_tr[period - 1] = tr[:period].sum()
    smoothed_plus_dm[period - 1] = plus_dm[:period].sum()
    smoothed_minus_dm[period - 1] = minus_dm[:period].sum()
    for i in range(period, n):
        smoothed_tr[i] = smoothed_tr[i - 1] - smoothed_tr[i - 1] / period + tr[i]
        smoothed_plus_dm[i] = (
            smoothed_plus_dm[i - 1] - smoothed_plus_dm[i - 1] / period + plus_dm[i]
        )
        smoothed_minus_dm[i] = (
            smoothed_minus_dm[i - 1] - smoothed_minus_dm[i - 1] / period + minus_dm[i]
        )

    plus_di = np.divide(
        100.0 * smoothed_plus_dm,
        smoothed_tr,
        out=np.zeros_like(smoothed_tr),
        where=smoothed_tr != 0,
    )
    minus_di = np.divide(
        100.0 * smoothed_minus_dm,
        smoothed_tr,
        out=np.zeros_like(smoothed_tr),
        where=smoothed_tr != 0,
    )
    di_sum = plus_di + minus_di
    dx = np.divide(
        100.0 * np.abs(plus_di - minus_di),
        di_sum,
        out=np.zeros_like(di_sum),
        where=di_sum != 0,
    )

    adx_values = np.zeros(n)
    if n >= 2 * period - 1:
        adx_values[2 * period - 2] = dx[period - 1 : 2 * period - 1].mean()
        for i in range(2 * period - 1, n):
            adx_values[i] = (adx_values[i - 1] * (period - 1) + dx[i]) / period

    valid_start = 2 * period - 2
    return ADXResult(
        timestamp=datetime.now(UTC),
        bars_used=len(bars),
        latest_adx=to_decimal(float(adx_values[-1])),
        latest_plus_di=to_decimal(float(plus_di[-1])),
        latest_minus_di=to_decimal(float(minus_di[-1])),
        series_adx=decimal_series(adx_values[valid_start:]),
        series_plus_di=decimal_series(plus_di[valid_start:]),
        series_minus_di=decimal_series(minus_di[valid_start:]),
        period=period,
    )


def detect_crossover(
    fast_series: list[Decimal],
    slow_series: list[Decimal],
    lookback: int = 3,
) -> CrossoverState:
    """Most-recent crossover within `lookback` bars."""
    if len(fast_series) < 2 or len(slow_series) < 2:
        return "none"
    n = min(len(fast_series), len(slow_series))
    start = max(1, n - lookback)
    for i in range(n - 1, start - 1, -1):
        prev_fast, prev_slow = fast_series[i - 1], slow_series[i - 1]
        curr_fast, curr_slow = fast_series[i], slow_series[i]
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            return "crossed_above"
        if prev_fast >= prev_slow and curr_fast < curr_slow:
            return "crossed_below"
    return "none"


def above_200_sma(bars: list[Bar]) -> bool:
    """Convenience for the 6-rule strategy gate "price above 200-SMA on daily."""
    if len(bars) < 200:
        raise InsufficientBarsError(required=200, got=len(bars))
    sma200 = sma(bars, period=200)
    return Decimal(str(bars[-1].close)) > sma200.latest
