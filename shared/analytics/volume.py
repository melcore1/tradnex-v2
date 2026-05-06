"""Volume analytics: VWAP, volume vs average."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import numpy as np

from shared.analytics.base import (
    IndicatorResult,
    InsufficientBarsError,
    closes_array,
    decimal_series,
    highs_array,
    lows_array,
    to_decimal,
    volumes_array,
)
from shared.schemas.market import Bar


class VWAPResult(IndicatorResult):
    latest: Decimal
    series: list[Decimal]


class VolumeRatioResult(IndicatorResult):
    latest_ratio: Decimal
    today_volume: int
    avg_volume: int
    period: int


def vwap(bars: list[Bar]) -> VWAPResult:
    """Cumulative VWAP over the input bars (intra-session use case)."""
    if not bars:
        raise InsufficientBarsError(required=1, got=0)
    highs = highs_array(bars)
    lows = lows_array(bars)
    closes = closes_array(bars)
    volumes = volumes_array(bars)
    typical = (highs + lows + closes) / 3.0
    cum_pv = np.cumsum(typical * volumes)
    cum_v = np.cumsum(volumes)
    vwap_values = np.where(cum_v > 0, cum_pv / cum_v, typical)
    return VWAPResult(
        timestamp=datetime.now(UTC),
        bars_used=len(bars),
        latest=to_decimal(float(vwap_values[-1])),
        series=decimal_series(vwap_values),
    )


def volume_vs_avg(bars: list[Bar], period: int = 30) -> VolumeRatioResult:
    if len(bars) < period + 1:
        raise InsufficientBarsError(required=period + 1, got=len(bars))
    volumes = volumes_array(bars)
    today = int(volumes[-1])
    avg = int(volumes[-(period + 1) : -1].mean())
    ratio = today / avg if avg > 0 else 0.0
    return VolumeRatioResult(
        timestamp=datetime.now(UTC),
        bars_used=len(bars),
        latest_ratio=to_decimal(ratio),
        today_volume=today,
        avg_volume=avg,
        period=period,
    )
