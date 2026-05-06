"""Volatility indicator tests: ATR, Bollinger, GARCH, Monte Carlo."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
import ta

from shared.analytics import (
    InsufficientBarsError,
    garch_forecast,
    monte_carlo,
)
from shared.analytics import (
    atr as atr_func,
)
from shared.analytics import (
    bollinger as bollinger_func,
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


def _walk(n: int, seed: int = 42, start: float = 100.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return start + np.cumsum(rng.normal(0.0, 1.0, n))


def test_atr_matches_ta_library() -> None:
    closes = _walk(60)
    bars = _make_bars(closes)
    df = pd.DataFrame(
        {
            "high": [float(b.high) for b in bars],
            "low": [float(b.low) for b in bars],
            "close": [float(b.close) for b in bars],
        }
    )
    our = atr_func(bars, period=14)
    expected = float(
        ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14)
        .average_true_range()
        .dropna()
        .iloc[-1]
    )
    assert abs(float(our.latest) - expected) < 0.05


def test_atr_pct_of_spot_in_reasonable_range() -> None:
    bars = _make_bars(_walk(60))
    result = atr_func(bars)
    # Random walk ~$1 sigma on $100 start → ATR pct should be small but positive
    assert Decimal("0") < result.latest_pct_of_spot < Decimal("10")


def test_atr_insufficient_bars() -> None:
    with pytest.raises(InsufficientBarsError):
        atr_func(_make_bars(_walk(10)), period=14)


def test_bollinger_matches_ta_library() -> None:
    closes = _walk(60)
    bars = _make_bars(closes)
    our = bollinger_func(bars, period=20, std_dev=2.0)
    bb = ta.volatility.BollingerBands(pd.Series(closes), window=20, window_dev=2)
    expected_upper = float(bb.bollinger_hband().dropna().iloc[-1])
    expected_middle = float(bb.bollinger_mavg().dropna().iloc[-1])
    expected_lower = float(bb.bollinger_lband().dropna().iloc[-1])
    assert abs(float(our.latest_upper) - expected_upper) < 0.05
    assert abs(float(our.latest_middle) - expected_middle) < 0.05
    assert abs(float(our.latest_lower) - expected_lower) < 0.05


def test_bollinger_bandwidth_decreases_on_low_vol_data() -> None:
    flat = _make_bars([100.0] * 30)
    flat_result = bollinger_func(flat)
    # Flat data → bandwidth ~0
    assert flat_result.bandwidth_pct < Decimal("0.1")


def test_bollinger_position_inside_bands() -> None:
    bars = _make_bars(_walk(40))
    result = bollinger_func(bars)
    # Position should be roughly 0-100 for any close that's between the bands
    assert Decimal("-50") < result.position < Decimal("150")


def test_bollinger_insufficient_bars() -> None:
    with pytest.raises(InsufficientBarsError):
        bollinger_func(_make_bars(_walk(10)), period=20)


def test_garch_fits_on_random_walk() -> None:
    # Use enough bars and gentle vol to ensure convergence
    rng = np.random.default_rng(7)
    closes = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 200)))
    bars = _make_bars(closes)
    result = garch_forecast(bars, horizon=5)
    # Sanity: persistence in (0, 1), forecast positive
    assert Decimal("0") < result.persistence < Decimal("1")
    assert result.annualized_vol_forecast > Decimal("0")
    assert len(result.forecast_path) == 5


def test_garch_insufficient_bars() -> None:
    bars = _make_bars(_walk(20))
    with pytest.raises(InsufficientBarsError):
        garch_forecast(bars)


def test_monte_carlo_median_near_spot_for_short_horizon() -> None:
    rng = np.random.default_rng(7)
    closes = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 200)))
    bars = _make_bars(closes)
    garch_r = garch_forecast(bars)
    mc = monte_carlo(bars, garch_r, n_paths=5_000, horizon=5)
    spot = float(bars[-1].close)
    # 5d median should be within ±10% of spot for typical vol
    assert abs(float(mc.percentiles[50]) - spot) / spot < 0.10
    # Probabilities should sum sensibly
    assert Decimal("0") <= mc.prob_above_current <= Decimal("1")


def test_monte_carlo_percentile_ordering() -> None:
    rng = np.random.default_rng(7)
    closes = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 200)))
    bars = _make_bars(closes)
    garch_r = garch_forecast(bars)
    mc = monte_carlo(bars, garch_r, n_paths=5_000, horizon=5)
    # Percentiles must be monotonically increasing
    p_values = [mc.percentiles[p] for p in (5, 10, 25, 50, 75, 90, 95)]
    assert p_values == sorted(p_values)


def test_monte_carlo_deterministic_with_seed() -> None:
    rng = np.random.default_rng(7)
    closes = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 200)))
    bars = _make_bars(closes)
    garch_r = garch_forecast(bars)
    mc1 = monte_carlo(bars, garch_r, n_paths=1_000, horizon=5, seed=999)
    mc2 = monte_carlo(bars, garch_r, n_paths=1_000, horizon=5, seed=999)
    assert mc1.percentiles[50] == mc2.percentiles[50]
    assert mc1.mean == mc2.mean
