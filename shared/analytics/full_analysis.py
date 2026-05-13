"""Full-analysis aggregator: every Tier 2 analytic from one ticker's bars."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, computed_field

from shared.analytics.base import GARCHFitError
from shared.analytics.levels import (
    FibonacciResult,
    SupportResistanceResult,
    fibonacci,
    support_resistance,
)
from shared.analytics.momentum import MACDResult, RSIResult, macd, rsi
from shared.analytics.regime import RegimeState, RegimeThresholds, classify_regime
from shared.analytics.trend import (
    ADXResult,
    CrossoverState,
    EMAResult,
    SMAResult,
    adx,
    detect_crossover,
    ema,
    sma,
)
from shared.analytics.volatility import (
    ATRResult,
    BollingerResult,
    GARCHResult,
    MonteCarloResult,
    atr,
    bollinger,
    garch_forecast,
    monte_carlo,
)
from shared.analytics.volume import VWAPResult, vwap
from shared.schemas.market import Bar

if TYPE_CHECKING:
    from shared.analytics.options.full_options_analysis import FullOptionsAnalysis


class FullAnalysis(BaseModel):
    """Everything the scanner, evaluator, and journal need from one ticker's bars."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    spot: Decimal
    timestamp: datetime
    bars_count: int
    timeframe: str

    rsi: RSIResult
    macd: MACDResult

    ema9: EMAResult
    ema21: EMAResult
    sma50: SMAResult
    sma200: SMAResult | None
    adx: ADXResult
    ema9_21_crossover: CrossoverState
    sma50_200_crossover: CrossoverState
    # Tri-state: True/False when 200+ bars available, None when we can't compute
    # SMA200 yet (e.g. scout called with days_history < 200). Downstream consumers
    # must distinguish "price below 200-SMA" (False) from "insufficient data"
    # (None) before treating this as a strategy gate.
    above_200_sma: bool | None

    atr: ATRResult
    bollinger: BollingerResult
    garch: GARCHResult | None
    monte_carlo: MonteCarloResult | None

    fibonacci: FibonacciResult
    support_resistance: SupportResistanceResult

    vwap: VWAPResult | None

    regime: RegimeState | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> str:
        parts = [f"{self.ticker} at {self.spot}"]
        parts.append(f"RSI {self.rsi.latest} {self.rsi.trend}")
        macd_state = "bullish" if self.macd.line_above_signal else "bearish"
        parts.append(f"MACD {macd_state} {self.macd.histogram_trend}")
        if self.above_200_sma is None:
            parts.append("200-SMA n/a")
        else:
            parts.append("above 200-SMA" if self.above_200_sma else "below 200-SMA")
        parts.append(
            "EMA9>EMA21" if self.ema9.latest > self.ema21.latest else "EMA9<EMA21"
        )
        parts.append(f"ATR {self.atr.regime}")
        if self.support_resistance.nearest_resistance is not None:
            parts.append(f"near resistance {self.support_resistance.nearest_resistance}")
        if self.regime is not None:
            parts.append(f"regime {self.regime.overall} (conf {self.regime.confidence})")
        return ", ".join(parts)


async def compute_full_analysis(
    ticker: str,
    bars: list[Bar],
    timeframe: str = "1d",
    options_analysis: FullOptionsAnalysis | None = None,
    regime_thresholds: RegimeThresholds | None = None,
    spot_override: Decimal | None = None,
) -> FullAnalysis:
    """Compute every Tier 2 analytic plus the regime state from a ticker's bars.

    Synchronous indicators run inline. GARCH fit (the slow one) is dispatched
    to a worker thread via asyncio.to_thread() so concurrent compute calls
    don't serialize on it.

    Pass `options_analysis` to enrich the regime classifier with gamma + IV
    components; otherwise those components fall back to 'unknown'.

    Pass `spot_override` when a live quote is already available (e.g. from
    quick_check which fetches a quote in parallel with bars). The summary
    string and `spot` field will use this value instead of `bars[-1].close`
    — the latter can lag the live price by a few points when the most
    recent daily bar is still being written or hasn't ticked over.
    """
    if not bars:
        raise ValueError("bars must not be empty")

    rsi_r = rsi(bars, period=14)
    macd_r = macd(bars)
    ema9_r = ema(bars, period=9)
    ema21_r = ema(bars, period=21)
    sma50_r = sma(bars, period=50)
    sma200_r: SMAResult | None
    above_200: bool | None = None
    if len(bars) >= 200:
        sma200_r = sma(bars, period=200)
        above_200 = Decimal(str(bars[-1].close)) > sma200_r.latest
    else:
        sma200_r = None
    adx_r = adx(bars)
    atr_r = atr(bars)
    bollinger_r = bollinger(bars)
    fibonacci_r = fibonacci(bars, lookback=min(50, len(bars)))
    sr_r = support_resistance(bars, lookback=min(100, len(bars)))
    vwap_r = vwap(bars) if timeframe != "1d" else None

    ema9_21 = detect_crossover(ema9_r.series, ema21_r.series, lookback=3)
    sma50_200: CrossoverState = (
        detect_crossover(sma50_r.series, sma200_r.series, lookback=3)
        if sma200_r is not None
        else "none"
    )

    garch_r: GARCHResult | None
    monte_carlo_r: MonteCarloResult | None = None
    try:
        garch_r = await asyncio.to_thread(garch_forecast, bars)
        monte_carlo_r = monte_carlo(bars, garch_r)
    except (GARCHFitError, Exception):
        garch_r = None
        monte_carlo_r = None

    spot = (
        spot_override
        if spot_override is not None
        else Decimal(str(bars[-1].close))
    )
    partial = FullAnalysis(
        ticker=ticker.upper(),
        spot=spot,
        timestamp=datetime.now(UTC),
        bars_count=len(bars),
        timeframe=timeframe,
        rsi=rsi_r,
        macd=macd_r,
        ema9=ema9_r,
        ema21=ema21_r,
        sma50=sma50_r,
        sma200=sma200_r,
        adx=adx_r,
        ema9_21_crossover=ema9_21,
        sma50_200_crossover=sma50_200,
        above_200_sma=above_200,
        atr=atr_r,
        bollinger=bollinger_r,
        garch=garch_r,
        monte_carlo=monte_carlo_r,
        fibonacci=fibonacci_r,
        support_resistance=sr_r,
        vwap=vwap_r,
        regime=None,
    )

    thresholds = regime_thresholds or RegimeThresholds()
    regime_state = classify_regime(partial, options_analysis, bars, thresholds)
    return partial.model_copy(update={"regime": regime_state})
