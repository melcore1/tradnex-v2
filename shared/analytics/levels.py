"""Price-level analytics: Fibonacci retracement/extension, support/resistance."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, computed_field

from shared.analytics.base import (
    IndicatorResult,
    InsufficientBarsError,
    closes_array,
    highs_array,
    lows_array,
    to_decimal,
)
from shared.schemas.market import Bar

RETRACEMENT_RATIOS = (
    Decimal("0"),
    Decimal("0.236"),
    Decimal("0.382"),
    Decimal("0.5"),
    Decimal("0.618"),
    Decimal("0.786"),
    Decimal("1"),
)
EXTENSION_RATIOS = (
    Decimal("1.272"),
    Decimal("1.618"),
    Decimal("2"),
    Decimal("2.618"),
)


class FibonacciResult(IndicatorResult):
    swing_high: Decimal
    swing_low: Decimal
    swing_direction: Literal["up", "down"]
    swing_high_bar_idx: int
    swing_low_bar_idx: int
    retracements: dict[Decimal, Decimal]
    extensions: dict[Decimal, Decimal]
    current_position_pct: Decimal
    lookback: int


class Level(BaseModel):
    model_config = ConfigDict(frozen=True)
    price: Decimal
    touches: int
    last_touched_bar_idx: int


class SupportResistanceResult(IndicatorResult):
    support_levels: list[Level]
    resistance_levels: list[Level]
    nearest_support: Decimal | None
    nearest_resistance: Decimal | None
    lookback: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def current_position(self) -> Literal["near_support", "near_resistance", "mid_range"]:
        # Best-effort: the caller knows current spot; we approximate from the
        # gap between nearest support and nearest resistance. Without spot we
        # cannot compute precisely, so return mid_range when ambiguous.
        if self.nearest_support is None and self.nearest_resistance is None:
            return "mid_range"
        if self.nearest_support is not None and self.nearest_resistance is None:
            return "near_support"
        if self.nearest_resistance is not None and self.nearest_support is None:
            return "near_resistance"
        return "mid_range"


def fibonacci(bars: list[Bar], lookback: int = 50) -> FibonacciResult:
    if len(bars) < 2:
        raise InsufficientBarsError(required=2, got=len(bars))
    if lookback < 2:
        raise ValueError("lookback must be >= 2")

    window_bars = bars[-lookback:]
    highs = highs_array(window_bars)
    lows = lows_array(window_bars)
    high_local_idx = int(np.argmax(highs))
    low_local_idx = int(np.argmin(lows))
    swing_high = float(highs[high_local_idx])
    swing_low = float(lows[low_local_idx])

    # Direction: which swing point is more recent
    swing_direction: Literal["up", "down"] = "up" if low_local_idx < high_local_idx else "down"

    # Bar idx in the original `bars` array
    base_idx = len(bars) - len(window_bars)
    swing_high_bar_idx = base_idx + high_local_idx
    swing_low_bar_idx = base_idx + low_local_idx

    swing_range = swing_high - swing_low
    if swing_range <= 0:
        # Flat data — synthesize trivial levels
        retracements = {ratio: to_decimal(swing_high) for ratio in RETRACEMENT_RATIOS}
        extensions = {ratio: to_decimal(swing_high) for ratio in EXTENSION_RATIOS}
        current_position_pct = to_decimal(0.0)
    else:
        if swing_direction == "up":
            # Retracement levels measured down from swing_high toward swing_low
            retracements = {
                ratio: to_decimal(swing_high - float(ratio) * swing_range)
                for ratio in RETRACEMENT_RATIOS
            }
            extensions = {
                ratio: to_decimal(swing_high + (float(ratio) - 1.0) * swing_range)
                for ratio in EXTENSION_RATIOS
            }
        else:
            # Down swing — measured up from swing_low toward swing_high
            retracements = {
                ratio: to_decimal(swing_low + float(ratio) * swing_range)
                for ratio in RETRACEMENT_RATIOS
            }
            extensions = {
                ratio: to_decimal(swing_low - (float(ratio) - 1.0) * swing_range)
                for ratio in EXTENSION_RATIOS
            }
        spot = float(bars[-1].close)
        current_position_pct = to_decimal((spot - swing_low) / swing_range * 100.0)

    return FibonacciResult(
        timestamp=datetime.now(UTC),
        bars_used=len(bars),
        swing_high=to_decimal(swing_high),
        swing_low=to_decimal(swing_low),
        swing_direction=swing_direction,
        swing_high_bar_idx=swing_high_bar_idx,
        swing_low_bar_idx=swing_low_bar_idx,
        retracements=retracements,
        extensions=extensions,
        current_position_pct=current_position_pct,
        lookback=lookback,
    )


def _find_pivots(prices: np.ndarray, side: str, window: int = 5) -> list[tuple[int, float]]:
    pivots: list[tuple[int, float]] = []
    n = len(prices)
    for i in range(window, n - window):
        local = prices[i - window : i + window + 1]
        if side == "high" and prices[i] == local.max():
            pivots.append((i, float(prices[i])))
        elif side == "low" and prices[i] == local.min():
            pivots.append((i, float(prices[i])))
    return pivots


def _cluster_levels(
    pivots: list[tuple[int, float]],
    tolerance_pct: Decimal,
) -> list[Level]:
    if not pivots:
        return []
    sorted_pivots = sorted(pivots, key=lambda x: x[1])
    clusters: list[list[tuple[int, float]]] = [[sorted_pivots[0]]]
    tol = float(tolerance_pct)
    for piv in sorted_pivots[1:]:
        last = clusters[-1][-1][1]
        if last == 0 or abs(piv[1] - last) / last * 100.0 < tol:
            clusters[-1].append(piv)
        else:
            clusters.append([piv])

    levels: list[Level] = []
    for cluster in clusters:
        avg_price = float(np.mean([p[1] for p in cluster]))
        last_idx = max(p[0] for p in cluster)
        levels.append(
            Level(
                price=to_decimal(avg_price),
                touches=len(cluster),
                last_touched_bar_idx=last_idx,
            )
        )
    return levels


def support_resistance(
    bars: list[Bar],
    lookback: int = 100,
    min_touches: int = 2,
    tolerance_pct: Decimal = Decimal("0.5"),
    pivot_window: int = 5,
) -> SupportResistanceResult:
    if len(bars) < pivot_window * 2 + 1:
        raise InsufficientBarsError(required=pivot_window * 2 + 1, got=len(bars))

    window_bars = bars[-lookback:]
    base_idx = len(bars) - len(window_bars)
    highs = highs_array(window_bars)
    lows = lows_array(window_bars)
    closes = closes_array(window_bars)

    high_pivots = [(base_idx + i, p) for i, p in _find_pivots(highs, "high", pivot_window)]
    low_pivots = [(base_idx + i, p) for i, p in _find_pivots(lows, "low", pivot_window)]

    high_levels = [
        lvl
        for lvl in _cluster_levels(high_pivots, tolerance_pct)
        if lvl.touches >= min_touches
    ]
    low_levels = [
        lvl
        for lvl in _cluster_levels(low_pivots, tolerance_pct)
        if lvl.touches >= min_touches
    ]

    spot = float(closes[-1])
    support_levels = sorted(
        [lvl for lvl in low_levels if float(lvl.price) <= spot],
        key=lambda x: float(x.price),
        reverse=True,
    )
    resistance_levels = sorted(
        [lvl for lvl in high_levels if float(lvl.price) >= spot],
        key=lambda x: float(x.price),
    )

    nearest_support = support_levels[0].price if support_levels else None
    nearest_resistance = resistance_levels[0].price if resistance_levels else None

    return SupportResistanceResult(
        timestamp=datetime.now(UTC),
        bars_used=len(bars),
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        nearest_support=nearest_support,
        nearest_resistance=nearest_resistance,
        lookback=lookback,
    )
