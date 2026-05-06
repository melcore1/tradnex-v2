"""Levels analytics tests: Fibonacci, support/resistance."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from shared.analytics import (
    InsufficientBarsError,
    fibonacci,
    support_resistance,
)
from shared.schemas.market import Bar


def _make_bars(closes, seed: int = 1) -> list[Bar]:
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


def test_fibonacci_detects_swing_up() -> None:
    # Constructed: low at start, high at end → swing direction "up"
    closes = list(np.linspace(100, 150, 50))
    bars = _make_bars(closes)
    result = fibonacci(bars, lookback=50)
    assert result.swing_direction == "up"
    assert float(result.swing_low) <= 100.5
    assert float(result.swing_high) >= 149.5


def test_fibonacci_detects_swing_down() -> None:
    closes = list(np.linspace(150, 100, 50))
    bars = _make_bars(closes)
    result = fibonacci(bars, lookback=50)
    assert result.swing_direction == "down"


def test_fibonacci_retracements_at_known_ratios() -> None:
    # Hand-crafted: low 100, high 200 → 50% retracement = 150
    closes = list(np.linspace(100, 200, 50))
    bars = _make_bars(closes)
    result = fibonacci(bars, lookback=50)
    fifty_pct = result.retracements[Decimal("0.5")]
    # On up swing, 50% retracement = high - 0.5 * range = 200 - 0.5 * 100 = 150
    assert abs(float(fifty_pct) - 150.0) < 1.5  # synthesized OHLC adds noise


def test_fibonacci_extension_beyond_swing_high() -> None:
    closes = list(np.linspace(100, 200, 50))
    bars = _make_bars(closes)
    result = fibonacci(bars, lookback=50)
    one_six_one_eight = result.extensions[Decimal("1.618")]
    # 161.8% extension on up swing = high + 0.618 * range = 200 + 0.618 * 100 = ~261.8
    assert float(one_six_one_eight) > 200


def test_fibonacci_lookback_configurable() -> None:
    closes = list(np.linspace(100, 200, 100))
    bars = _make_bars(closes)
    short = fibonacci(bars, lookback=20)
    long = fibonacci(bars, lookback=80)
    # Different lookbacks pick different swing windows → different swing low usually
    assert short.lookback == 20
    assert long.lookback == 80


def test_fibonacci_insufficient_bars() -> None:
    with pytest.raises(InsufficientBarsError):
        fibonacci(_make_bars([100.0]), lookback=50)


def test_support_resistance_finds_repeated_levels() -> None:
    # Crafted scenario: oscillates between 100 and 110, multiple touches each
    closes = []
    for _ in range(20):
        closes.extend([100.0, 102.0, 105.0, 108.0, 110.0, 108.0, 105.0, 102.0])
    bars = _make_bars(closes)
    result = support_resistance(bars, lookback=len(bars), min_touches=2, tolerance_pct=Decimal("2"))
    assert len(result.support_levels) + len(result.resistance_levels) > 0


def test_support_resistance_insufficient_bars() -> None:
    with pytest.raises(InsufficientBarsError):
        support_resistance(_make_bars([100.0] * 5), pivot_window=5)


def test_support_resistance_classifies_above_below() -> None:
    # Final close around 105 — levels above are resistance, below are support
    closes = []
    for _ in range(15):
        closes.extend([100.0, 102.0, 105.0, 108.0, 110.0, 108.0, 105.0, 102.0])
    closes.append(105.5)  # last close
    bars = _make_bars(closes)
    result = support_resistance(bars, min_touches=2, tolerance_pct=Decimal("2"))
    if result.nearest_resistance is not None:
        assert float(result.nearest_resistance) >= 105.5
    if result.nearest_support is not None:
        assert float(result.nearest_support) <= 105.5
