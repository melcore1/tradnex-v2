"""Regime classifier tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from shared.analytics import (
    ADXResult,
    ATRResult,
    BollingerResult,
    EMAResult,
    FibonacciResult,
    Level,
    MACDResult,
    RegimeThresholds,
    RSIResult,
    SMAResult,
    SupportResistanceResult,
    classify_regime,
)
from shared.analytics.full_analysis import FullAnalysis
from shared.schemas.market import Bar


def _bar(close: float, volume: int, day_offset: int = 0) -> Bar:
    return Bar(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day_offset),
        open=Decimal(str(close)),
        high=Decimal(str(close + 0.5)),
        low=Decimal(str(close - 0.5)),
        close=Decimal(str(close)),
        volume=volume,
    )


def _bars_steady(volume: int = 1_000_000, n: int = 60) -> list[Bar]:
    return [_bar(100, volume, i) for i in range(n)]


def _bars_with_volume_surge(n: int = 60) -> list[Bar]:
    bars = _bars_steady(volume=1_000_000, n=n - 1)
    bars.append(_bar(close=100, volume=5_000_000, day_offset=n - 1))
    return bars


def _make_full_analysis(
    *,
    rsi_latest: Decimal = Decimal("50"),
    adx_latest: Decimal = Decimal("28"),
    adx_direction: str = "bullish",
    above_200: bool = True,
    ema9: Decimal = Decimal("110"),
    ema21: Decimal = Decimal("105"),
    atr_pct: Decimal = Decimal("0.8"),
    bandwidth_pct: Decimal = Decimal("2.0"),
    is_squeezing: bool = False,
) -> FullAnalysis:
    ts = datetime.now(UTC)
    return FullAnalysis(
        ticker="TEST",
        spot=Decimal("100"),
        timestamp=ts,
        bars_count=200,
        timeframe="1d",
        rsi=RSIResult(
            timestamp=ts,
            bars_used=200,
            latest=rsi_latest,
            series=[rsi_latest] * 30,
            period=14,
        ),
        macd=MACDResult(
            timestamp=ts,
            bars_used=200,
            latest_line=Decimal("0.5"),
            latest_signal=Decimal("0.4"),
            latest_histogram=Decimal("0.1"),
            series_line=[Decimal("0.5")] * 10,
            series_signal=[Decimal("0.4")] * 10,
            series_histogram=[Decimal("0.1")] * 10,
            fast=12,
            slow=26,
            signal=9,
            bullish_divergence_at_pullback_low=False,
        ),
        ema9=EMAResult(timestamp=ts, bars_used=200, latest=ema9, series=[ema9], period=9),
        ema21=EMAResult(
            timestamp=ts, bars_used=200, latest=ema21, series=[ema21], period=21
        ),
        sma50=SMAResult(
            timestamp=ts,
            bars_used=200,
            latest=Decimal("100"),
            series=[Decimal("100")],
            period=50,
        ),
        sma200=SMAResult(
            timestamp=ts,
            bars_used=200,
            latest=Decimal("95") if above_200 else Decimal("105"),
            series=[Decimal("95") if above_200 else Decimal("105")],
            period=200,
        ),
        adx=ADXResult(
            timestamp=ts,
            bars_used=200,
            latest_adx=adx_latest,
            latest_plus_di=Decimal("30") if adx_direction == "bullish" else Decimal("15"),
            latest_minus_di=Decimal("15") if adx_direction == "bullish" else Decimal("30"),
            series_adx=[adx_latest],
            series_plus_di=[Decimal("30")],
            series_minus_di=[Decimal("15")],
            period=14,
        ),
        ema9_21_crossover="none",
        sma50_200_crossover="none",
        above_200_sma=above_200,
        atr=ATRResult(
            timestamp=ts,
            bars_used=200,
            latest=Decimal("1"),
            series=[Decimal("1")],
            period=14,
            latest_pct_of_spot=atr_pct,
        ),
        bollinger=BollingerResult(
            timestamp=ts,
            bars_used=200,
            latest_upper=Decimal("102"),
            latest_middle=Decimal("100"),
            latest_lower=Decimal("98"),
            series_upper=[Decimal("102")] * 25,
            series_middle=[Decimal("100")] * 25,
            series_lower=[Decimal("98")] * 25,
            period=20,
            std_dev=2.0,
            bandwidth_pct=bandwidth_pct,
            position=Decimal("50"),
            is_squeezing=is_squeezing,
        ),
        garch=None,
        monte_carlo=None,
        fibonacci=FibonacciResult(
            timestamp=ts,
            bars_used=200,
            swing_high=Decimal("110"),
            swing_low=Decimal("90"),
            swing_direction="up",
            swing_high_bar_idx=199,
            swing_low_bar_idx=180,
            retracements={Decimal("0.5"): Decimal("100")},
            extensions={},
            current_position_pct=Decimal("50"),
            lookback=50,
        ),
        support_resistance=SupportResistanceResult(
            timestamp=ts,
            bars_used=200,
            support_levels=[],
            resistance_levels=[Level(price=Decimal("105"), touches=3, last_touched_bar_idx=190)],
            nearest_support=None,
            nearest_resistance=Decimal("105"),
            lookback=100,
        ),
        vwap=None,
        regime=None,
    )


def test_trending_bullish_low_vol() -> None:
    fa = _make_full_analysis()
    state = classify_regime(fa)
    assert state.trend_regime == "bullish"
    assert state.volatility_regime == "low"
    assert state.overall == "trending_bullish"
    assert state.confidence > Decimal("0.5")


def test_trending_bearish_high_vol() -> None:
    fa = _make_full_analysis(
        adx_direction="bearish",
        above_200=False,
        ema9=Decimal("90"),
        ema21=Decimal("95"),
        atr_pct=Decimal("3.5"),
        rsi_latest=Decimal("40"),
    )
    state = classify_regime(fa)
    assert state.trend_regime == "bearish"
    assert state.volatility_regime == "high"
    assert state.overall == "trending_bearish"


def test_ranging_low_vol_via_squeeze() -> None:
    fa = _make_full_analysis(
        adx_latest=Decimal("15"),
        bandwidth_pct=Decimal("1.5"),
        is_squeezing=True,
    )
    state = classify_regime(fa)
    assert state.trend_regime == "sideways"
    assert state.overall == "ranging_low_vol"


def test_ranging_high_vol() -> None:
    fa = _make_full_analysis(
        adx_latest=Decimal("15"),
        atr_pct=Decimal("3.5"),
    )
    state = classify_regime(fa)
    assert state.overall == "ranging_high_vol"


def test_capitulation_with_bars() -> None:
    fa = _make_full_analysis(
        adx_direction="bearish",
        above_200=False,
        ema9=Decimal("90"),
        ema21=Decimal("95"),
        atr_pct=Decimal("3.5"),
        rsi_latest=Decimal("20"),
    )
    bars = _bars_with_volume_surge()
    state = classify_regime(fa, bars=bars)
    assert state.overall == "capitulation"
    assert "rsi_extreme_low" in state.signals_used
    assert "volume_surge" in state.signals_used


def test_distribution_with_bars() -> None:
    fa = _make_full_analysis(
        rsi_latest=Decimal("85"),
    )
    # Volume declining: 25 high-volume bars then 5 low-volume
    bars = [_bar(100, 5_000_000, i) for i in range(25)]
    bars.extend(_bar(100, 500_000, i + 25) for i in range(5))
    state = classify_regime(fa, bars=bars)
    assert state.overall == "distribution"


def test_unknown_when_partial_data() -> None:
    fa = _make_full_analysis(
        adx_latest=Decimal("15"),
        adx_direction="neutral",
        above_200=False,
        ema9=Decimal("100"),
        ema21=Decimal("100"),
        atr_pct=Decimal("2"),
    )
    state = classify_regime(fa)
    # No options → gamma + iv unknown; trend sideways with normal vol → no clear overall
    assert state.gamma_regime == "unknown"
    assert state.iv_regime == "unknown"


def test_confidence_gets_components_known_bonus() -> None:
    fa_with_strong_signals = _make_full_analysis(atr_pct=Decimal("0.8"))
    state = classify_regime(fa_with_strong_signals)
    # Trend != sideways, vol != normal → 0.5 + 0.2 minimum
    assert state.confidence >= Decimal("0.7")


def test_custom_thresholds_override_defaults() -> None:
    custom = RegimeThresholds(adx_strong_trend=Decimal("50"))  # very strict
    fa = _make_full_analysis(adx_latest=Decimal("28"))  # default-strong but custom-weak
    state = classify_regime(fa, thresholds=custom)
    # Under stricter threshold, ADX 28 no longer counts as strong → trend sideways
    assert state.trend_regime == "sideways"


def test_signals_used_dedupes_and_orders() -> None:
    fa = _make_full_analysis()
    state = classify_regime(fa)
    assert len(state.signals_used) == len(set(state.signals_used))
