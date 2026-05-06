"""Configurable strategy parameters.

Defaults are calibrated for the long-options-momentum entry rules. Phase 7
will load runtime overrides from `strategy_configs.settings_json`.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ShortlistParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    delta_target_low: Decimal = Decimal("0.25")
    delta_target_high: Decimal = Decimal("0.35")
    min_dte: int = 3
    max_dte: int = 14
    max_total_contracts: int = 5
    max_per_bucket: int = 2
    min_buckets: int = 2
    liquidity_score_min: int = 1000


class MarketWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    scanner_start: str = "09:45"
    scanner_end: str = "15:00"
    monitor_start: str = "09:30"
    monitor_end: str = "15:55"


class EvaluatorSettings(BaseModel):
    """Phase 5: Claude evaluator + Exa news + queue + LLM bypass switch."""

    model_config = ConfigDict(frozen=True)

    # Subprocess / model
    claude_model: str = "claude-opus-4-7"
    claude_timeout_seconds: int = 90
    claude_max_turns: int = 1

    # Queue + poller
    max_concurrent_evaluations: int = 3
    poll_interval_seconds: int = 300
    poll_age_threshold_seconds: int = 600

    # Exa pre-fetch
    exa_news_lookback_days: int = 7
    exa_news_max_articles: int = 3

    # LLM bypass switch — when False, scanner picks contract via
    # select_default_contract and the evaluator runs the rule-based
    # fallback (no Claude call).
    llm_enabled: bool = True

    # Guardrails
    prompt_token_budget: int = 60_000  # rough char/4 budget
    delta_target_range_low: Decimal = Decimal("0.30")
    delta_target_range_high: Decimal = Decimal("0.70")


class StrategySettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_premium: Decimal = Decimal("500")
    sizing_multipliers: dict[str, Decimal] = Field(
        default_factory=lambda: {
            "STRONG": Decimal("1.0"),
            "MODERATE": Decimal("0.66"),
            "WEAK": Decimal("0.4"),
        }
    )

    volume_mult_base_threshold: Decimal = Decimal("1.2")
    volume_mult_bonus_threshold: Decimal = Decimal("2.0")
    rsi_sweet_spot_low: Decimal = Decimal("50")
    rsi_sweet_spot_high: Decimal = Decimal("65")
    adx_base_threshold: Decimal = Decimal("20")
    adx_bonus_threshold: Decimal = Decimal("25")

    shortlist_params: ShortlistParams = Field(default_factory=ShortlistParams)
    market_window: MarketWindow = Field(default_factory=MarketWindow)
    evaluator: EvaluatorSettings = Field(default_factory=EvaluatorSettings)
