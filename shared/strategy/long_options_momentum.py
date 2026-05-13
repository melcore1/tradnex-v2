"""Long Options Momentum: the 3-hard-rule + 3-soft-rule entry strategy.

Hard rules (all must pass):
    H1: price above 200-SMA on daily
    H2: EMA9 > EMA21 on 5-min
    H3: MACD bullish divergence at pullback low (5-min)

Soft rules (scored 0/1/2 each → 0-6 total):
    S1: Volume confirmation
    S2: RSI rising (with sweet-spot bonus)
    S3: ADX strength (with bullish direction bonus)

Soft score → confidence:
    5-6: STRONG, 3-4: MODERATE, 1-2: WEAK, 0: VETO (no candidate)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from shared.analytics.base import InsufficientBarsError
from shared.analytics.full_analysis import FullAnalysis
from shared.analytics.momentum import macd as compute_macd
from shared.analytics.options.full_options_analysis import FullOptionsAnalysis
from shared.analytics.regime import RegimeState
from shared.analytics.trend import ema as compute_ema
from shared.analytics.volume import volume_vs_avg
from shared.schemas.market import Bar, OptionContract
from shared.strategy.base import (
    ConfidenceLabel,
    EntryCandidate,
    RuleResult,
    RuleTrace,
    RuleType,
)
from shared.strategy.settings import StrategySettings


def select_default_contract(
    shortlist: list[OptionContract],
    delta_target_range: tuple[Decimal, Decimal],
) -> OptionContract | None:
    """Phase 5 fallback: pick a contract deterministically when LLM is
    disabled or unavailable.

    Algorithm:
      1. Filter shortlist to contracts whose abs(delta) is within
         `delta_target_range`.
      2. Of those, return the one with the highest open_interest * volume
         (liquidity score). Ties broken by tighter bid-ask spread.
      3. If nothing fits the delta band, return None.
    """
    low, high = delta_target_range
    in_range = [
        c for c in shortlist
        if low <= abs(c.delta) <= high
    ]
    if not in_range:
        return None
    return max(
        in_range,
        key=lambda c: (
            int(c.open_interest) * int(c.volume),
            -float(c.ask - c.bid),
        ),
    )


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _override(overrides: dict[str, Any], key: str, default: Decimal) -> Decimal:
    """Pick override value (coerced to Decimal) or default."""
    if key in overrides:
        return _to_decimal(overrides[key])
    return default


class LongOptionsMomentum:
    """The 6-rule long-call momentum strategy. v1: long_call only."""

    name = "long_options_momentum"

    def __init__(self, settings: StrategySettings | None = None) -> None:
        self.settings = settings or StrategySettings()

    # ---- Hard rules --------------------------------------------------------

    def _evaluate_h1_above_200_sma(
        self,
        full_analysis: FullAnalysis,
    ) -> RuleResult:
        above = full_analysis.above_200_sma
        passed = above is True
        sma200 = (
            full_analysis.sma200.latest if full_analysis.sma200 is not None else None
        )
        if above is None:
            failure_reason: str | None = "200-SMA unavailable (need 200+ daily bars)"
        elif above:
            failure_reason = None
        else:
            failure_reason = "price below or at 200-SMA on daily"
        return RuleResult(
            name="H1_above_200_sma",
            rule_type=RuleType.HARD,
            passed=passed,
            score=1 if passed else 0,
            max_score=1,
            details={
                "close": str(full_analysis.spot),
                "sma200": str(sma200) if sma200 is not None else None,
            },
            failure_reason=failure_reason,
        )

    def _evaluate_h2_ema_alignment(
        self,
        bars_5m: list[Bar],
    ) -> RuleResult:
        try:
            ema9 = compute_ema(bars_5m, period=9)
            ema21 = compute_ema(bars_5m, period=21)
        except InsufficientBarsError as e:
            return RuleResult(
                name="H2_ema9_above_ema21_5m",
                rule_type=RuleType.HARD,
                passed=False,
                score=0,
                max_score=1,
                details={"error": str(e), "bars_count": len(bars_5m)},
                failure_reason="insufficient 5-min bars for EMA21",
            )
        passed = ema9.latest > ema21.latest
        return RuleResult(
            name="H2_ema9_above_ema21_5m",
            rule_type=RuleType.HARD,
            passed=passed,
            score=1 if passed else 0,
            max_score=1,
            details={"ema9": str(ema9.latest), "ema21": str(ema21.latest)},
            failure_reason=None if passed else "EMA9 not above EMA21 on 5-min",
        )

    def _evaluate_h3_macd_divergence(
        self,
        bars_5m: list[Bar],
    ) -> RuleResult:
        try:
            macd_r = compute_macd(bars_5m)
        except InsufficientBarsError as e:
            return RuleResult(
                name="H3_macd_bullish_divergence_5m",
                rule_type=RuleType.HARD,
                passed=False,
                score=0,
                max_score=1,
                details={"error": str(e), "bars_count": len(bars_5m)},
                failure_reason="insufficient 5-min bars for MACD",
            )
        passed = bool(macd_r.bullish_divergence_at_pullback_low)
        return RuleResult(
            name="H3_macd_bullish_divergence_5m",
            rule_type=RuleType.HARD,
            passed=passed,
            score=1 if passed else 0,
            max_score=1,
            details={
                "divergence_detected": passed,
                "lookback": 20,
                "histogram_latest": str(macd_r.latest_histogram),
            },
            failure_reason=None if passed else "no MACD bullish divergence at pullback",
        )

    # ---- Soft rules --------------------------------------------------------

    def _evaluate_s1_volume(
        self,
        bars_daily: list[Bar],
        overrides: dict[str, Any],
    ) -> RuleResult:
        base = _override(
            overrides,
            "volume_mult_min",
            self.settings.volume_mult_base_threshold,
        )
        bonus = _override(
            overrides,
            "volume_mult_bonus",
            self.settings.volume_mult_bonus_threshold,
        )
        try:
            vol_r = volume_vs_avg(bars_daily, period=30)
        except InsufficientBarsError as e:
            return RuleResult(
                name="S1_volume_confirmation",
                rule_type=RuleType.SOFT,
                passed=False,
                score=0,
                max_score=2,
                details={"error": str(e), "bars_count": len(bars_daily)},
                failure_reason="insufficient daily bars for 30-day volume average",
            )
        ratio = vol_r.latest_ratio
        score = 0
        if ratio > bonus:
            score = 2
        elif ratio > base:
            score = 1
        return RuleResult(
            name="S1_volume_confirmation",
            rule_type=RuleType.SOFT,
            passed=score > 0,
            score=score,
            max_score=2,
            details={
                "vol_ratio": str(ratio),
                "today_volume": vol_r.today_volume,
                "avg_volume": vol_r.avg_volume,
                "base_threshold": str(base),
                "bonus_threshold": str(bonus),
            },
            failure_reason=None
            if score > 0
            else f"volume ratio {ratio} <= {base}",
        )

    def _evaluate_s2_rsi_rising(
        self,
        full_analysis: FullAnalysis,
        overrides: dict[str, Any],
    ) -> RuleResult:
        sweet_low = _override(
            overrides, "rsi_min", self.settings.rsi_sweet_spot_low
        )
        sweet_high = _override(
            overrides, "rsi_max", self.settings.rsi_sweet_spot_high
        )
        rsi = full_analysis.rsi
        rising = rsi.trend == "rising"
        in_sweet_spot = sweet_low <= rsi.latest <= sweet_high
        score = 0
        if rising and in_sweet_spot:
            score = 2
        elif rising:
            score = 1
        return RuleResult(
            name="S2_rsi_rising",
            rule_type=RuleType.SOFT,
            passed=score > 0,
            score=score,
            max_score=2,
            details={
                "rsi": str(rsi.latest),
                "trend": rsi.trend,
                "in_sweet_spot": in_sweet_spot,
                "sweet_spot_low": str(sweet_low),
                "sweet_spot_high": str(sweet_high),
            },
            failure_reason=None
            if score > 0
            else f"RSI trend={rsi.trend} (need 'rising')",
        )

    def _evaluate_s3_adx_strength(
        self,
        full_analysis: FullAnalysis,
        overrides: dict[str, Any],
    ) -> RuleResult:
        base = _override(
            overrides, "adx_min", self.settings.adx_base_threshold
        )
        bonus = _override(
            overrides, "adx_bonus", self.settings.adx_bonus_threshold
        )
        adx = full_analysis.adx
        adx_val = adx.latest_adx
        is_bullish = adx.direction == "bullish"
        score = 0
        if adx_val > bonus and is_bullish:
            score = 2
        elif adx_val > base:
            score = 1
        return RuleResult(
            name="S3_adx_strength",
            rule_type=RuleType.SOFT,
            passed=score > 0,
            score=score,
            max_score=2,
            details={
                "adx": str(adx_val),
                "plus_di": str(adx.latest_plus_di),
                "minus_di": str(adx.latest_minus_di),
                "direction": adx.direction,
                "base_threshold": str(base),
                "bonus_threshold": str(bonus),
            },
            failure_reason=None
            if score > 0
            else f"ADX {adx_val} <= {base}",
        )

    # ---- Aggregator --------------------------------------------------------

    def _confidence_from_score(self, score: int) -> ConfidenceLabel:
        if score >= 5:
            return "STRONG"
        if score >= 3:
            return "MODERATE"
        if score >= 1:
            return "WEAK"
        return "VETO"

    async def evaluate_entry(
        self,
        ticker: str,
        bars_5m: list[Bar],
        bars_daily: list[Bar],
        full_analysis: FullAnalysis,
        options_analysis: FullOptionsAnalysis | None,
        regime: RegimeState,
        overrides: dict[str, Any],
    ) -> tuple[RuleTrace, EntryCandidate | None]:
        """Evaluate the 6 rules. Always returns a trace; candidate is None
        when any hard rule fails OR soft score is 0."""
        h1 = self._evaluate_h1_above_200_sma(full_analysis)
        h2 = self._evaluate_h2_ema_alignment(bars_5m)
        h3 = self._evaluate_h3_macd_divergence(bars_5m)
        hard = [h1, h2, h3]
        all_hard_passed = all(r.passed for r in hard)

        s1 = self._evaluate_s1_volume(bars_daily, overrides)
        s2 = self._evaluate_s2_rsi_rising(full_analysis, overrides)
        s3 = self._evaluate_s3_adx_strength(full_analysis, overrides)
        soft = [s1, s2, s3]
        soft_score = sum(r.score for r in soft)
        soft_max_score = sum(r.max_score for r in soft)

        if not all_hard_passed:
            label: ConfidenceLabel = "VETO"
            fired = False
            reason = "hard_rule_failed:" + ",".join(
                r.name for r in hard if not r.passed
            )
        else:
            label = self._confidence_from_score(soft_score)
            fired = label != "VETO"
            reason = (
                f"all_hard_passed_soft_score_{soft_score}"
                if fired
                else "all_hard_passed_but_no_soft_confirmation"
            )

        confidence_score = (
            Decimal(soft_score) / Decimal(soft_max_score)
            if soft_max_score > 0
            else Decimal("0")
        )

        rule_trace = RuleTrace(
            timestamp=datetime.now(UTC),
            ticker=ticker.upper(),
            hard_rules=hard,
            soft_rules=soft,
            all_hard_passed=all_hard_passed,
            soft_score=soft_score,
            soft_max_score=soft_max_score,
            confidence_label=label,
            confidence_score=confidence_score,
            fired=fired,
            fire_decision_reason=reason,
        )

        if not fired:
            return rule_trace, None

        confidence: ConfidenceLabel = label  # narrowed by fired check
        assert confidence in ("STRONG", "MODERATE", "WEAK")
        sizing_multiplier = self.settings.sizing_multipliers[confidence]
        candidate = EntryCandidate(
            ticker=ticker.upper(),
            direction="long_call",
            strategy_name=self.name,
            rule_trace=rule_trace,
            full_analysis=full_analysis,
            options_analysis=options_analysis,
            regime=regime,
            overrides_applied=dict(overrides),
            confidence=confidence,
            sizing_multiplier=sizing_multiplier,
            max_premium=self.settings.max_premium,
            shortlist=None,
            timestamp=datetime.now(UTC),
        )
        return rule_trace, candidate
