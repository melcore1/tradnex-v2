"""Regime classification: composite categorical state per ticker.

Combines Tier 2 (full_analysis) with Tier 3 (options_analysis) into a single
label that the scanner / orchestrator / Claude evaluator consume.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

if TYPE_CHECKING:
    from shared.analytics.full_analysis import FullAnalysis
    from shared.analytics.options.full_options_analysis import FullOptionsAnalysis
    from shared.schemas.market import Bar


TrendRegime = Literal["bullish", "bearish", "sideways"]
VolRegime = Literal["low", "normal", "high", "extreme"]
GammaRegime = Literal["positive_gamma", "negative_gamma", "flip_zone", "unknown"]
IVRegimeLabel = Literal["low", "normal", "high", "unknown"]
OverallRegime = Literal[
    "trending_bullish",
    "trending_bearish",
    "ranging_low_vol",
    "ranging_high_vol",
    "breakout_up",
    "breakout_down",
    "capitulation",
    "distribution",
    "unknown",
]


class RegimeThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    adx_strong_trend: Decimal = Decimal("25")
    adx_weak_trend: Decimal = Decimal("20")
    atr_pct_high_threshold: Decimal = Decimal("3.0")
    atr_pct_low_threshold: Decimal = Decimal("1.0")
    atr_pct_extreme_threshold: Decimal = Decimal("5.0")
    bollinger_squeeze_threshold: Decimal = Decimal("3.0")
    iv_rank_high_threshold: Decimal = Decimal("70")
    iv_rank_low_threshold: Decimal = Decimal("30")
    rsi_extreme_low: Decimal = Decimal("25")
    rsi_extreme_high: Decimal = Decimal("80")
    volume_surge_ratio: Decimal = Decimal("2.0")
    volume_decline_ratio: Decimal = Decimal("0.7")
    component_agreement_bonus: Decimal = Decimal("0.2")


class RegimeState(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    timestamp: datetime
    overall: OverallRegime
    trend_regime: TrendRegime
    volatility_regime: VolRegime
    gamma_regime: GammaRegime
    iv_regime: IVRegimeLabel
    confidence: Decimal
    signals_used: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def description(self) -> str:
        match self.overall:
            case "trending_bullish":
                return (
                    f"{self.ticker} trending bullish; volatility {self.volatility_regime}, "
                    f"dealer gamma {self.gamma_regime}, IV {self.iv_regime}"
                )
            case "trending_bearish":
                return (
                    f"{self.ticker} trending bearish; volatility {self.volatility_regime}, "
                    f"dealer gamma {self.gamma_regime}, IV {self.iv_regime}"
                )
            case "ranging_low_vol":
                return f"{self.ticker} ranging in low volatility (Bollinger squeeze)"
            case "ranging_high_vol":
                return f"{self.ticker} ranging in high volatility (chop)"
            case "breakout_up":
                return f"{self.ticker} breaking out to the upside on volume"
            case "breakout_down":
                return f"{self.ticker} breaking down on volume"
            case "capitulation":
                return f"{self.ticker} capitulating: oversold + heavy volume after downtrend"
            case "distribution":
                return f"{self.ticker} distributing: overbought + declining volume in uptrend"
            case "unknown":
                return f"{self.ticker} regime unknown (insufficient data)"


def _trend(full: FullAnalysis, t: RegimeThresholds) -> tuple[TrendRegime, list[str]]:
    used: list[str] = []
    adx_val = full.adx.latest_adx
    direction = full.adx.direction
    above_200 = full.above_200_sma
    ema9_above = full.ema9.latest > full.ema21.latest
    used.append("adx_strength")
    used.append("ema_alignment")
    used.append("above_200_sma")
    if (
        adx_val >= t.adx_strong_trend
        and direction == "bullish"
        and above_200 is True
        and ema9_above
    ):
        return "bullish", used
    if (
        adx_val >= t.adx_strong_trend
        and direction == "bearish"
        and above_200 is False
        and not ema9_above
    ):
        return "bearish", used
    return "sideways", used


def _volatility(full: FullAnalysis, t: RegimeThresholds) -> tuple[VolRegime, list[str]]:
    pct = full.atr.latest_pct_of_spot
    if pct >= t.atr_pct_extreme_threshold:
        return "extreme", ["atr_pct"]
    if pct >= t.atr_pct_high_threshold:
        return "high", ["atr_pct"]
    if pct < t.atr_pct_low_threshold:
        return "low", ["atr_pct"]
    return "normal", ["atr_pct"]


def _gamma(options: FullOptionsAnalysis | None) -> tuple[GammaRegime, list[str]]:
    if options is None:
        return "unknown", []
    return options.gex.regime, ["gex_regime"]


def _iv(options: FullOptionsAnalysis | None) -> tuple[IVRegimeLabel, list[str]]:
    if options is None or options.iv_rank is None or options.iv_rank.regime is None:
        return "unknown", []
    return options.iv_rank.regime, ["iv_rank_regime"]


def _volume_surge(bars: list[Bar] | None, ratio_threshold: Decimal) -> bool:
    if bars is None or len(bars) < 30:
        return False
    recent = bars[-1].volume
    avg = sum(b.volume for b in bars[-30:-1]) / 29 if len(bars) >= 30 else 0
    return avg > 0 and Decimal(recent) / Decimal(int(avg)) >= ratio_threshold


def _volume_declining(bars: list[Bar] | None, ratio_threshold: Decimal) -> bool:
    if bars is None or len(bars) < 30:
        return False
    recent_5 = sum(b.volume for b in bars[-5:])
    prior_25 = sum(b.volume for b in bars[-30:-5]) / 25 * 5
    if prior_25 <= 0:
        return False
    return Decimal(recent_5) / Decimal(int(prior_25)) <= ratio_threshold


def _bollinger_recently_expanded(full: FullAnalysis) -> bool:
    series = full.bollinger.series_upper
    series_lower = full.bollinger.series_lower
    series_mid = full.bollinger.series_middle
    if len(series) < 6 or len(series_mid) < 6:
        return False
    if series_mid[-1] != 0:
        recent_bw = (series[-1] - series_lower[-1]) / series_mid[-1]
    else:
        recent_bw = Decimal("0")
    if series_mid[-6] != 0:
        prior_bw = (series[-6] - series_lower[-6]) / series_mid[-6]
    else:
        prior_bw = Decimal("0")
    return recent_bw > prior_bw * Decimal("1.3")


DEFAULT_REGIME_THRESHOLDS = RegimeThresholds()


def classify_regime(
    full_analysis: FullAnalysis,
    options_analysis: FullOptionsAnalysis | None = None,
    bars: list[Bar] | None = None,
    thresholds: RegimeThresholds = DEFAULT_REGIME_THRESHOLDS,
) -> RegimeState:
    """Compose the four component regimes into an overall categorical state.

    Decision tree (documented in plan):
      - trend: bullish / bearish / sideways from ADX + 200-SMA + EMA9/21
      - volatility: low / normal / high / extreme from ATR % of spot
      - gamma: SpotGamma regime, or 'unknown' if no options input
      - iv: IV-rank regime, or 'unknown' if no IV history

    Overall composes these plus optional bar-based volume + RSI signals
    (capitulation, distribution, breakout). When bars are missing, those
    overall states aren't reachable.
    """
    trend, trend_signals = _trend(full_analysis, thresholds)
    vol, vol_signals = _volatility(full_analysis, thresholds)
    gamma, gamma_signals = _gamma(options_analysis)
    iv, iv_signals = _iv(options_analysis)
    signals: list[str] = trend_signals + vol_signals + gamma_signals + iv_signals

    overall: OverallRegime = "unknown"
    rsi_latest = full_analysis.rsi.latest
    capitulation = (
        trend == "bearish"
        and rsi_latest < thresholds.rsi_extreme_low
        and _volume_surge(bars, thresholds.volume_surge_ratio)
    )
    distribution = (
        trend == "bullish"
        and rsi_latest > thresholds.rsi_extreme_high
        and _volume_declining(bars, thresholds.volume_decline_ratio)
    )
    breakout_volume = _volume_surge(bars, thresholds.volume_surge_ratio)
    bb_expanded = _bollinger_recently_expanded(full_analysis)
    closing_lower = bars is not None and len(bars) >= 2 and bars[-1].close < bars[-2].close

    if capitulation:
        overall = "capitulation"
        signals.append("rsi_extreme_low")
        signals.append("volume_surge")
    elif distribution:
        overall = "distribution"
        signals.append("rsi_extreme_high")
        signals.append("volume_declining")
    elif (
        trend in ("bullish", "sideways")
        and bb_expanded
        and breakout_volume
        and not closing_lower
    ):
        overall = "breakout_up"
        signals.append("bollinger_expanded")
        signals.append("volume_surge")
    elif (
        trend in ("bearish", "sideways")
        and bb_expanded
        and breakout_volume
        and closing_lower
    ):
        overall = "breakout_down"
        signals.append("bollinger_expanded")
        signals.append("volume_surge")
        signals.append("closing_lower")
    elif trend == "bullish" and vol in ("low", "normal") and gamma in ("positive_gamma", "unknown"):
        overall = "trending_bullish"
    elif trend == "bearish" and vol in ("normal", "high", "extreme"):
        overall = "trending_bearish"
    elif trend == "sideways" and (
        vol == "low" or full_analysis.bollinger.is_squeezing
    ):
        overall = "ranging_low_vol"
        if full_analysis.bollinger.is_squeezing:
            signals.append("bollinger_squeezing")
    elif trend == "sideways" and vol in ("high", "extreme"):
        overall = "ranging_high_vol"

    confidence = Decimal("0.5")
    components_known = 0
    if trend != "sideways":
        components_known += 1
    if vol != "normal":
        components_known += 1
    if gamma != "unknown":
        components_known += 1
    if iv != "unknown":
        components_known += 1
    confidence += Decimal("0.1") * Decimal(components_known)

    if (
        trend == "bullish"
        and vol in ("low", "normal")
        and gamma == "positive_gamma"
        and iv == "low"
    ):
        confidence += thresholds.component_agreement_bonus
    elif (
        trend == "bearish"
        and vol in ("high", "extreme")
        and gamma == "negative_gamma"
        and iv == "high"
    ):
        confidence += thresholds.component_agreement_bonus

    confidence = min(confidence, Decimal("1.0"))

    return RegimeState(
        ticker=full_analysis.ticker,
        timestamp=datetime.now(UTC),
        overall=overall,
        trend_regime=trend,
        volatility_regime=vol,
        gamma_regime=gamma,
        iv_regime=iv,
        confidence=confidence,
        signals_used=list(dict.fromkeys(signals)),  # dedup, preserve order
    )
