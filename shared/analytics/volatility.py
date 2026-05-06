"""Volatility indicators: ATR, Bollinger Bands, GARCH, Monte Carlo."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import numpy as np
from pydantic import computed_field

from shared.analytics.base import (
    GARCHFitError,
    IndicatorResult,
    InsufficientBarsError,
    closes_array,
    decimal_series,
    highs_array,
    lows_array,
    to_decimal,
    true_range,
    wilder_smooth,
)
from shared.schemas.market import Bar


class ATRResult(IndicatorResult):
    latest: Decimal
    series: list[Decimal]
    period: int
    latest_pct_of_spot: Decimal

    @computed_field  # type: ignore[prop-decorator]
    @property
    def regime(self) -> Literal["low", "normal", "high"]:
        if self.latest_pct_of_spot < Decimal("1"):
            return "low"
        if self.latest_pct_of_spot < Decimal("3"):
            return "normal"
        return "high"


class BollingerResult(IndicatorResult):
    latest_upper: Decimal
    latest_middle: Decimal
    latest_lower: Decimal
    series_upper: list[Decimal]
    series_middle: list[Decimal]
    series_lower: list[Decimal]
    period: int
    std_dev: float
    bandwidth_pct: Decimal
    position: Decimal
    is_squeezing: bool


class GARCHResult(IndicatorResult):
    annualized_vol_forecast: Decimal
    forecast_horizon: int
    forecast_path: list[Decimal]
    omega: Decimal
    alpha: Decimal
    beta: Decimal
    persistence: Decimal
    half_life: Decimal | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def regime(self) -> Literal["low_vol", "normal", "high_vol"]:
        # Annualized vol bands roughly aligned with broad market norms
        if self.annualized_vol_forecast < Decimal("0.20"):
            return "low_vol"
        if self.annualized_vol_forecast < Decimal("0.40"):
            return "normal"
        return "high_vol"


class MonteCarloResult(IndicatorResult):
    spot: Decimal
    n_paths: int
    horizon: int
    percentiles: dict[int, Decimal]
    mean: Decimal
    prob_above_current: Decimal
    prob_above_5pct: Decimal
    prob_below_5pct: Decimal
    expected_move_pct: Decimal

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bias(self) -> Literal["bullish", "bearish", "neutral"]:
        if self.prob_above_current > Decimal("0.55"):
            return "bullish"
        if self.prob_above_current < Decimal("0.45"):
            return "bearish"
        return "neutral"


def atr(bars: list[Bar], period: int = 14) -> ATRResult:
    if len(bars) < period + 1:
        raise InsufficientBarsError(required=period + 1, got=len(bars))

    highs = highs_array(bars)
    lows = lows_array(bars)
    closes = closes_array(bars)
    tr = true_range(highs, lows, closes)
    atr_values = wilder_smooth(tr, period)
    valid = atr_values[period - 1 :]

    spot = float(bars[-1].close)
    latest = float(valid[-1])
    pct = (latest / spot * 100.0) if spot > 0 else 0.0

    return ATRResult(
        timestamp=datetime.now(UTC),
        bars_used=len(bars),
        latest=to_decimal(latest),
        series=decimal_series(valid),
        period=period,
        latest_pct_of_spot=to_decimal(pct),
    )


def bollinger(
    bars: list[Bar],
    period: int = 20,
    std_dev: float = 2.0,
) -> BollingerResult:
    if len(bars) < period:
        raise InsufficientBarsError(required=period, got=len(bars))

    closes = closes_array(bars)
    n = len(closes)
    middle = np.zeros(n)
    upper = np.zeros(n)
    lower = np.zeros(n)
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        m = window.mean()
        s = window.std(ddof=0)
        middle[i] = m
        upper[i] = m + std_dev * s
        lower[i] = m - std_dev * s

    valid = slice(period - 1, None)
    spot = float(bars[-1].close)
    latest_upper = float(upper[-1])
    latest_middle = float(middle[-1])
    latest_lower = float(lower[-1])
    bandwidth = (
        (latest_upper - latest_lower) / latest_middle * 100.0 if latest_middle > 0 else 0.0
    )
    position = (
        (spot - latest_lower) / (latest_upper - latest_lower) * 100.0
        if latest_upper != latest_lower
        else 50.0
    )
    bw_series = (upper[valid] - lower[valid]) / np.where(
        middle[valid] > 0, middle[valid], 1.0
    ) * 100.0
    is_squeezing = bool(
        len(bw_series) >= 20 and bandwidth < float(bw_series[-20:].mean()) * 0.8
    )

    return BollingerResult(
        timestamp=datetime.now(UTC),
        bars_used=len(bars),
        latest_upper=to_decimal(latest_upper),
        latest_middle=to_decimal(latest_middle),
        latest_lower=to_decimal(latest_lower),
        series_upper=decimal_series(upper[valid]),
        series_middle=decimal_series(middle[valid]),
        series_lower=decimal_series(lower[valid]),
        period=period,
        std_dev=std_dev,
        bandwidth_pct=to_decimal(bandwidth),
        position=to_decimal(position),
        is_squeezing=is_squeezing,
    )


def garch_forecast(bars: list[Bar], horizon: int = 5) -> GARCHResult:
    """GARCH(1,1) volatility forecast using the `arch` library.

    Input returns are scaled to percent and fit with rescale=False; output
    annualized vol is in decimal (e.g. 0.32 = 32%).
    """
    if len(bars) < 30:  # arch is unstable below ~30 returns
        raise InsufficientBarsError(required=30, got=len(bars))

    closes = closes_array(bars)
    if (closes <= 0).any():
        raise GARCHFitError("Non-positive close price encountered")
    log_returns_pct = np.diff(np.log(closes)) * 100.0

    try:
        from arch import arch_model

        model = arch_model(log_returns_pct, vol="GARCH", p=1, q=1, rescale=False)
        fit = model.fit(disp="off", show_warning=False)
    except Exception as e:  # convergence failure
        raise GARCHFitError(f"GARCH fit failed: {e}") from e

    forecast = fit.forecast(horizon=horizon, reindex=False)
    var_path_pct2 = np.asarray(forecast.variance.iloc[-1].values, dtype=np.float64)
    daily_vol_decimal_path = np.sqrt(var_path_pct2) / 100.0
    annualized_path = daily_vol_decimal_path * np.sqrt(252)
    annualized_mean = float(annualized_path.mean())

    omega = float(fit.params.get("omega", 0.0))
    alpha = float(fit.params.get("alpha[1]", 0.0))
    beta = float(fit.params.get("beta[1]", 0.0))
    persistence = alpha + beta
    half_life: Decimal | None = None
    if 0 < persistence < 1:
        half_life = to_decimal(float(np.log(0.5) / np.log(persistence)))

    return GARCHResult(
        timestamp=datetime.now(UTC),
        bars_used=len(bars),
        annualized_vol_forecast=to_decimal(annualized_mean),
        forecast_horizon=horizon,
        forecast_path=decimal_series(annualized_path),
        omega=to_decimal(omega, ndigits=6),
        alpha=to_decimal(alpha, ndigits=6),
        beta=to_decimal(beta, ndigits=6),
        persistence=to_decimal(persistence, ndigits=6),
        half_life=half_life,
    )


def monte_carlo(
    bars: list[Bar],
    vol_forecast: GARCHResult,
    n_paths: int = 10_000,
    horizon: int = 5,
    seed: int = 42,
) -> MonteCarloResult:
    rng = np.random.default_rng(seed)
    spot = float(bars[-1].close)
    annualized_vol = float(vol_forecast.annualized_vol_forecast)
    daily_vol = annualized_vol / float(np.sqrt(252))
    drift = -0.5 * daily_vol**2

    z = rng.standard_normal((n_paths, horizon))
    log_returns = drift + daily_vol * z
    cum = np.cumsum(log_returns, axis=1)
    paths = spot * np.exp(cum)
    final = paths[:, -1]

    pct_levels = [5, 10, 25, 50, 75, 90, 95]
    percentiles = {p: to_decimal(float(np.percentile(final, p))) for p in pct_levels}

    p84 = float(np.percentile(final, 84))
    p16 = float(np.percentile(final, 16))
    expected_move_pct = (p84 - p16) / 2 / spot * 100.0 if spot > 0 else 0.0

    return MonteCarloResult(
        timestamp=datetime.now(UTC),
        bars_used=len(bars),
        spot=to_decimal(spot),
        n_paths=n_paths,
        horizon=horizon,
        percentiles=percentiles,
        mean=to_decimal(float(final.mean())),
        prob_above_current=to_decimal(float((final > spot).mean())),
        prob_above_5pct=to_decimal(float((final > spot * 1.05).mean())),
        prob_below_5pct=to_decimal(float((final < spot * 0.95).mean())),
        expected_move_pct=to_decimal(expected_move_pct),
    )
