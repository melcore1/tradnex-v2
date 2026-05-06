"""LongOptionsMomentum: per-rule + aggregate behavior."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from unittest.mock import patch

import pytest

from shared.analytics.full_analysis import FullAnalysis, compute_full_analysis
from shared.analytics.momentum import MACDResult, RSIResult
from shared.analytics.trend import ADXResult
from shared.clients.mock_market_data import MockDataClient
from shared.schemas.market import Bar
from shared.strategy.base import RuleResult, RuleType
from shared.strategy.long_options_momentum import LongOptionsMomentum

# ---- Builders ----------------------------------------------------------------

def _make_rsi(latest: Decimal, trend: Literal["rising", "falling", "flat"]) -> RSIResult:
    if trend == "rising":
        series = [latest - Decimal("5"), latest - Decimal("3"), latest - Decimal("1"), latest]
    elif trend == "falling":
        series = [latest + Decimal("5"), latest + Decimal("3"), latest + Decimal("1"), latest]
    else:
        series = [latest, latest, latest, latest]
    return RSIResult(
        timestamp=datetime.now(UTC),
        bars_used=200,
        latest=latest,
        series=series,
        period=14,
    )


def _make_adx(
    adx_val: Decimal,
    direction: Literal["bullish", "bearish", "neutral"],
) -> ADXResult:
    if direction == "bullish":
        plus_di, minus_di = Decimal("25"), Decimal("15")
    elif direction == "bearish":
        plus_di, minus_di = Decimal("15"), Decimal("25")
    else:
        plus_di, minus_di = Decimal("20"), Decimal("20")
    return ADXResult(
        timestamp=datetime.now(UTC),
        bars_used=200,
        latest_adx=adx_val,
        latest_plus_di=plus_di,
        latest_minus_di=minus_di,
        series_adx=[adx_val],
        series_plus_di=[plus_di],
        series_minus_di=[minus_di],
        period=14,
    )


def _make_volume_bars(today_volume: int, avg_volume: int, n: int = 50) -> list[Bar]:
    bars: list[Bar] = []
    end = datetime(2026, 5, 5, tzinfo=UTC)
    for i in range(n):
        ts = end - timedelta(days=n - 1 - i)
        is_today = i == n - 1
        bars.append(
            Bar(
                timestamp=ts,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=today_volume if is_today else avg_volume,
            )
        )
    return bars


def _trending_5m_bars(n: int = 200, *, ascending: bool) -> list[Bar]:
    """Generate monotonically rising or falling 5-min bars for EMA tests."""
    end = datetime(2026, 5, 5, 20, 0, tzinfo=UTC)
    bars: list[Bar] = []
    for i in range(n):
        # ascending: closes go from 100 → 100 + n*0.1
        # descending: closes go from 100 → 100 - n*0.1
        offset = i * Decimal("0.1") if ascending else Decimal(str(-i * 0.1))
        close = Decimal("100") + offset
        bars.append(
            Bar(
                timestamp=end - timedelta(minutes=5 * (n - 1 - i)),
                open=close,
                high=close + Decimal("0.05"),
                low=close - Decimal("0.05"),
                close=close,
                volume=10_000,
            )
        )
    return bars


def _make_macd(divergence: bool) -> MACDResult:
    return MACDResult(
        timestamp=datetime.now(UTC),
        bars_used=200,
        latest_line=Decimal("0.50"),
        latest_signal=Decimal("0.30"),
        latest_histogram=Decimal("0.20"),
        series_line=[Decimal("0.50")] * 5,
        series_signal=[Decimal("0.30")] * 5,
        series_histogram=[Decimal("0.20")] * 5,
        fast=12,
        slow=26,
        signal=9,
        bullish_divergence_at_pullback_low=divergence,
    )


# ---- Fixture: baseline FullAnalysis ------------------------------------------

@pytest.fixture
async def baseline_fa() -> FullAnalysis:
    client = MockDataClient(seed=42)
    bars = await client.get_bars("NVDA", "1d", limit=300)
    return await compute_full_analysis("NVDA", bars, "1d")


# ---- Hard rules --------------------------------------------------------------

async def test_h1_pass_when_above_200_sma(baseline_fa: FullAnalysis) -> None:
    fa = baseline_fa.model_copy(update={"above_200_sma": True})
    result = LongOptionsMomentum()._evaluate_h1_above_200_sma(fa)
    assert result.passed
    assert result.score == 1
    assert result.rule_type == RuleType.HARD


async def test_h1_fail_when_below_200_sma(baseline_fa: FullAnalysis) -> None:
    fa = baseline_fa.model_copy(update={"above_200_sma": False})
    result = LongOptionsMomentum()._evaluate_h1_above_200_sma(fa)
    assert not result.passed
    assert result.failure_reason is not None


def test_h2_pass_with_ema9_above_ema21() -> None:
    bars = _trending_5m_bars(n=100, ascending=True)
    result = LongOptionsMomentum()._evaluate_h2_ema_alignment(bars)
    assert result.passed
    assert Decimal(result.details["ema9"]) > Decimal(result.details["ema21"])


def test_h2_fail_with_ema9_below_ema21() -> None:
    bars = _trending_5m_bars(n=100, ascending=False)
    result = LongOptionsMomentum()._evaluate_h2_ema_alignment(bars)
    assert not result.passed


def test_h3_pass_when_divergence_detected() -> None:
    bars = _trending_5m_bars(n=100, ascending=True)
    with patch(
        "shared.strategy.long_options_momentum.compute_macd",
        return_value=_make_macd(divergence=True),
    ):
        result = LongOptionsMomentum()._evaluate_h3_macd_divergence(bars)
    assert result.passed
    assert result.details["divergence_detected"] is True


def test_h3_fail_when_no_divergence() -> None:
    bars = _trending_5m_bars(n=100, ascending=True)
    with patch(
        "shared.strategy.long_options_momentum.compute_macd",
        return_value=_make_macd(divergence=False),
    ):
        result = LongOptionsMomentum()._evaluate_h3_macd_divergence(bars)
    assert not result.passed


# ---- Soft rules --------------------------------------------------------------

def test_s1_score_zero_when_low_volume() -> None:
    bars = _make_volume_bars(today_volume=500_000, avg_volume=1_000_000)
    result = LongOptionsMomentum()._evaluate_s1_volume(bars, {})
    assert result.score == 0


def test_s1_score_one_when_mid_volume() -> None:
    bars = _make_volume_bars(today_volume=1_500_000, avg_volume=1_000_000)
    result = LongOptionsMomentum()._evaluate_s1_volume(bars, {})
    assert result.score == 1


def test_s1_score_two_when_high_volume() -> None:
    bars = _make_volume_bars(today_volume=2_500_000, avg_volume=1_000_000)
    result = LongOptionsMomentum()._evaluate_s1_volume(bars, {})
    assert result.score == 2


def test_volume_override_raises_threshold() -> None:
    """--set volume_mult_min=1.5 makes 1.3x ratio fall below the bar."""
    bars = _make_volume_bars(today_volume=1_300_000, avg_volume=1_000_000)
    strategy = LongOptionsMomentum()
    assert strategy._evaluate_s1_volume(bars, {}).score == 1
    overridden = strategy._evaluate_s1_volume(bars, {"volume_mult_min": 1.5})
    assert overridden.score == 0
    assert Decimal(overridden.details["base_threshold"]) == Decimal("1.5")


async def test_s2_score_two_rising_in_sweet_spot(baseline_fa: FullAnalysis) -> None:
    fa = baseline_fa.model_copy(update={"rsi": _make_rsi(Decimal("60"), "rising")})
    result = LongOptionsMomentum()._evaluate_s2_rsi_rising(fa, {})
    assert result.score == 2
    assert result.details["in_sweet_spot"] is True


async def test_s2_score_one_rising_outside_sweet_spot(baseline_fa: FullAnalysis) -> None:
    fa = baseline_fa.model_copy(update={"rsi": _make_rsi(Decimal("75"), "rising")})
    result = LongOptionsMomentum()._evaluate_s2_rsi_rising(fa, {})
    assert result.score == 1
    assert result.details["in_sweet_spot"] is False


async def test_s2_score_zero_not_rising(baseline_fa: FullAnalysis) -> None:
    fa = baseline_fa.model_copy(update={"rsi": _make_rsi(Decimal("60"), "falling")})
    result = LongOptionsMomentum()._evaluate_s2_rsi_rising(fa, {})
    assert result.score == 0


async def test_s3_score_two_strong_bullish(baseline_fa: FullAnalysis) -> None:
    fa = baseline_fa.model_copy(update={"adx": _make_adx(Decimal("30"), "bullish")})
    result = LongOptionsMomentum()._evaluate_s3_adx_strength(fa, {})
    assert result.score == 2


async def test_s3_score_one_moderate(baseline_fa: FullAnalysis) -> None:
    fa = baseline_fa.model_copy(update={"adx": _make_adx(Decimal("22"), "bullish")})
    result = LongOptionsMomentum()._evaluate_s3_adx_strength(fa, {})
    assert result.score == 1


async def test_s3_score_zero_when_weak(baseline_fa: FullAnalysis) -> None:
    fa = baseline_fa.model_copy(update={"adx": _make_adx(Decimal("18"), "bullish")})
    result = LongOptionsMomentum()._evaluate_s3_adx_strength(fa, {})
    assert result.score == 0


# ---- Aggregate evaluate_entry ------------------------------------------------

def _passing_rule(name: str, rule_type: RuleType, score: int = 1) -> RuleResult:
    return RuleResult(
        name=name,
        rule_type=rule_type,
        passed=True,
        score=score,
        max_score=2 if rule_type == RuleType.SOFT else 1,
        details={},
    )


def _failing_rule(name: str, rule_type: RuleType) -> RuleResult:
    return RuleResult(
        name=name,
        rule_type=rule_type,
        passed=False,
        score=0,
        max_score=2 if rule_type == RuleType.SOFT else 1,
        details={},
        failure_reason="forced_fail",
    )


async def test_aggregate_one_hard_fails_no_candidate(baseline_fa: FullAnalysis) -> None:
    bars_5m = _trending_5m_bars(n=100, ascending=True)
    bars_daily = _make_volume_bars(today_volume=2_500_000, avg_volume=1_000_000)
    strategy = LongOptionsMomentum()
    fa = baseline_fa.model_copy(update={"above_200_sma": False})
    regime = baseline_fa.regime
    assert regime is not None
    trace, candidate = await strategy.evaluate_entry(
        ticker="NVDA",
        bars_5m=bars_5m,
        bars_daily=bars_daily,
        full_analysis=fa,
        options_analysis=None,
        regime=regime,
        overrides={},
    )
    assert candidate is None
    assert trace.fired is False
    assert trace.confidence_label == "VETO"
    assert "hard_rule_failed" in trace.fire_decision_reason


async def test_aggregate_strong_when_all_pass_high_score(
    baseline_fa: FullAnalysis,
) -> None:
    """Force all rules to pass via patches; verify STRONG candidate emitted."""
    strategy = LongOptionsMomentum()
    regime = baseline_fa.regime
    assert regime is not None

    with (
        patch.object(
            strategy,
            "_evaluate_h1_above_200_sma",
            return_value=_passing_rule("H1", RuleType.HARD),
        ),
        patch.object(
            strategy,
            "_evaluate_h2_ema_alignment",
            return_value=_passing_rule("H2", RuleType.HARD),
        ),
        patch.object(
            strategy,
            "_evaluate_h3_macd_divergence",
            return_value=_passing_rule("H3", RuleType.HARD),
        ),
        patch.object(
            strategy,
            "_evaluate_s1_volume",
            return_value=_passing_rule("S1", RuleType.SOFT, score=2),
        ),
        patch.object(
            strategy,
            "_evaluate_s2_rsi_rising",
            return_value=_passing_rule("S2", RuleType.SOFT, score=2),
        ),
        patch.object(
            strategy,
            "_evaluate_s3_adx_strength",
            return_value=_passing_rule("S3", RuleType.SOFT, score=2),
        ),
    ):
        trace, candidate = await strategy.evaluate_entry(
            ticker="NVDA",
            bars_5m=[],
            bars_daily=[],
            full_analysis=baseline_fa,
            options_analysis=None,
            regime=regime,
            overrides={},
        )
    assert candidate is not None
    assert candidate.confidence == "STRONG"
    assert trace.soft_score == 6
    assert trace.confidence_label == "STRONG"
    assert candidate.sizing_multiplier == Decimal("1.0")


async def test_aggregate_no_candidate_when_score_zero(
    baseline_fa: FullAnalysis,
) -> None:
    """All hard pass but score 0 → no candidate fired."""
    strategy = LongOptionsMomentum()
    regime = baseline_fa.regime
    assert regime is not None

    with (
        patch.object(
            strategy,
            "_evaluate_h1_above_200_sma",
            return_value=_passing_rule("H1", RuleType.HARD),
        ),
        patch.object(
            strategy,
            "_evaluate_h2_ema_alignment",
            return_value=_passing_rule("H2", RuleType.HARD),
        ),
        patch.object(
            strategy,
            "_evaluate_h3_macd_divergence",
            return_value=_passing_rule("H3", RuleType.HARD),
        ),
        patch.object(
            strategy,
            "_evaluate_s1_volume",
            return_value=_failing_rule("S1", RuleType.SOFT),
        ),
        patch.object(
            strategy,
            "_evaluate_s2_rsi_rising",
            return_value=_failing_rule("S2", RuleType.SOFT),
        ),
        patch.object(
            strategy,
            "_evaluate_s3_adx_strength",
            return_value=_failing_rule("S3", RuleType.SOFT),
        ),
    ):
        trace, candidate = await strategy.evaluate_entry(
            ticker="NVDA",
            bars_5m=[],
            bars_daily=[],
            full_analysis=baseline_fa,
            options_analysis=None,
            regime=regime,
            overrides={},
        )
    assert candidate is None
    assert trace.fired is False
    assert trace.confidence_label == "VETO"
    assert "no_soft_confirmation" in trace.fire_decision_reason


async def test_aggregate_moderate_when_score_3(
    baseline_fa: FullAnalysis,
) -> None:
    strategy = LongOptionsMomentum()
    regime = baseline_fa.regime
    assert regime is not None

    with (
        patch.object(
            strategy,
            "_evaluate_h1_above_200_sma",
            return_value=_passing_rule("H1", RuleType.HARD),
        ),
        patch.object(
            strategy,
            "_evaluate_h2_ema_alignment",
            return_value=_passing_rule("H2", RuleType.HARD),
        ),
        patch.object(
            strategy,
            "_evaluate_h3_macd_divergence",
            return_value=_passing_rule("H3", RuleType.HARD),
        ),
        patch.object(
            strategy,
            "_evaluate_s1_volume",
            return_value=_passing_rule("S1", RuleType.SOFT, score=2),
        ),
        patch.object(
            strategy,
            "_evaluate_s2_rsi_rising",
            return_value=_passing_rule("S2", RuleType.SOFT, score=1),
        ),
        patch.object(
            strategy,
            "_evaluate_s3_adx_strength",
            return_value=_failing_rule("S3", RuleType.SOFT),
        ),
    ):
        trace, candidate = await strategy.evaluate_entry(
            ticker="NVDA",
            bars_5m=[],
            bars_daily=[],
            full_analysis=baseline_fa,
            options_analysis=None,
            regime=regime,
            overrides={},
        )
    assert candidate is not None
    assert candidate.confidence == "MODERATE"
    assert candidate.sizing_multiplier == Decimal("0.66")
