"""Format TradNex analytics models as JSON-friendly dicts for MCP clients.

The analytics layer uses ``Decimal`` extensively for numeric stability. We
stringify Decimals to keep precision intact across the JSON-RPC boundary; the
LLM happily reads them as numbers.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shared.analytics.full_analysis import FullAnalysis
    from shared.analytics.options.full_options_analysis import FullOptionsAnalysis
    from shared.analytics.regime import RegimeState
    from shared.schemas.market import MoverEntry, Quote


def _s(value: Decimal | float | int | None) -> str | None:
    """Stringify a Decimal/number; preserve None."""
    if value is None:
        return None
    return str(value)


def format_quote(quote: Quote) -> dict[str, Any]:
    """Lightweight quote dict matching the legacy Scout `quick_check` shape.

    Keys chosen to minimize prompt churn for Claude.ai workflows that already
    call the previous Scout server.
    """
    return {
        "ticker": quote.ticker,
        "price": _s(quote.spot),
        "bid": _s(quote.bid),
        "ask": _s(quote.ask),
        "day_open": _s(quote.day_open),
        "day_high": _s(quote.day_high),
        "day_low": _s(quote.day_low),
        "prev_close": _s(quote.prev_close),
        "day_change": _s(quote.day_change),
        "day_change_pct": _s(quote.day_change_pct),
        "volume": quote.volume,
        "avg_volume_30d": quote.avg_volume_30d,
        "volume_vs_avg": _s(quote.volume_vs_avg),
        "is_market_open": quote.is_market_open,
        "as_of": quote.timestamp.isoformat(),
    }


def format_tier2(analysis: FullAnalysis) -> dict[str, Any]:
    """Flatten Tier 2 analytics for MCP responses."""
    bollinger = analysis.bollinger
    return {
        "rsi": {
            "latest": _s(analysis.rsi.latest),
            "trend": analysis.rsi.trend,
        },
        "macd": {
            "line": _s(analysis.macd.latest_line),
            "signal": _s(analysis.macd.latest_signal),
            "histogram": _s(analysis.macd.latest_histogram),
            "line_above_signal": analysis.macd.line_above_signal,
            "histogram_trend": analysis.macd.histogram_trend,
        },
        "trend": {
            "ema9": _s(analysis.ema9.latest),
            "ema21": _s(analysis.ema21.latest),
            "sma50": _s(analysis.sma50.latest),
            "sma200": _s(analysis.sma200.latest) if analysis.sma200 else None,
            "adx": _s(analysis.adx.latest_adx),
            "adx_strength": analysis.adx.trend_strength,
            "adx_direction": analysis.adx.direction,
            "ema9_21_crossover": analysis.ema9_21_crossover,
            "sma50_200_crossover": analysis.sma50_200_crossover,
            "above_200_sma": analysis.above_200_sma,
        },
        "volatility": {
            "atr": _s(analysis.atr.latest),
            "atr_pct_of_spot": _s(analysis.atr.latest_pct_of_spot),
            "atr_regime": analysis.atr.regime,
            "bollinger_upper": _s(bollinger.latest_upper),
            "bollinger_middle": _s(bollinger.latest_middle),
            "bollinger_lower": _s(bollinger.latest_lower),
            "bollinger_bandwidth_pct": _s(bollinger.bandwidth_pct),
            "bollinger_is_squeezing": bollinger.is_squeezing,
            "garch_annualized": (
                _s(analysis.garch.annualized_vol_forecast)
                if analysis.garch
                else None
            ),
        },
        "levels": {
            "support": [_s(lvl.price) for lvl in analysis.support_resistance.support_levels],
            "resistance": [
                _s(lvl.price) for lvl in analysis.support_resistance.resistance_levels
            ],
            "nearest_support": _s(analysis.support_resistance.nearest_support),
            "nearest_resistance": _s(analysis.support_resistance.nearest_resistance),
            "fibonacci_retracements": {
                _s(k): _s(v) for k, v in analysis.fibonacci.retracements.items()
            },
            "fibonacci_current_position_pct": _s(analysis.fibonacci.current_position_pct),
        },
        "vwap": _s(analysis.vwap.latest) if analysis.vwap else None,
    }


def format_tier3(options: FullOptionsAnalysis) -> dict[str, Any]:
    """Flatten Tier 3 options analytics."""
    front_max_pain = next(iter(options.max_pain_per_expiration.values()), None)
    front_expected_move = next(iter(options.expected_move_per_expiration.values()), None)
    return {
        "gex": {
            "net": _s(options.gex.net_gex),
            "regime": options.gex.regime,
            "dealer_position": options.gex.dealer_position,
            "gamma_flip": _s(options.gex.gamma_flip),
            "call_wall": _s(options.gex.call_wall),
            "put_wall": _s(options.gex.put_wall),
            "distance_to_call_wall_pct": _s(options.gex.distance_to_call_wall_pct),
            "distance_to_put_wall_pct": _s(options.gex.distance_to_put_wall_pct),
        },
        "iv_rank": {
            "rank": _s(options.iv_rank.rank),
            "current_iv": _s(options.iv_rank.current_iv),
            "min_iv": _s(options.iv_rank.iv_min_lookback),
            "max_iv": _s(options.iv_rank.iv_max_lookback),
            "data_points": options.iv_rank.data_points,
            "lookback_days": options.iv_rank.lookback_days,
            "regime": options.iv_rank.regime,
        },
        "iv_percentile": {
            "percentile": _s(options.iv_percentile.percentile),
            "data_points": options.iv_percentile.data_points,
        },
        "skew": (
            {
                "put_25d_iv": _s(options.skew.put_25d_iv),
                "call_25d_iv": _s(options.skew.call_25d_iv),
                "skew": _s(options.skew.skew),
                "regime": options.skew.regime,
            }
            if options.skew is not None
            else None
        ),
        "term_structure": (
            {
                "front_month_iv": _s(options.term_structure.front_month_iv),
                "back_month_iv": _s(options.term_structure.back_month_iv),
                "slope": _s(options.term_structure.slope),
                "regime": options.term_structure.regime,
            }
            if options.term_structure is not None
            else None
        ),
        "max_pain_front": (
            {
                "expiration": front_max_pain.expiration.isoformat(),
                "strike": _s(front_max_pain.max_pain_strike),
                "distance_pct": _s(front_max_pain.distance_pct),
                "regime": front_max_pain.regime,
            }
            if front_max_pain is not None
            else None
        ),
        "expected_move_front": (
            {
                "dte": front_expected_move.dte,
                "pct": _s(front_expected_move.expected_move_pct),
            }
            if front_expected_move is not None
            else None
        ),
        "pc_ratio": {
            "oi": _s(options.pc_ratio.oi_pc_ratio),
            "volume": _s(options.pc_ratio.volume_pc_ratio),
            "regime_oi": options.pc_ratio.regime_oi,
            "regime_volume": options.pc_ratio.regime_volume,
        },
        "unusual_activity_count": len(options.unusual_activity.flagged_contracts),
        "zero_dte": (
            {"pin_risk": options.zero_dte.pin_risk}
            if options.zero_dte is not None
            else None
        ),
    }


def format_regime(regime: RegimeState | None) -> dict[str, Any]:
    """Flatten the regime classifier output."""
    if regime is None:
        return {"overall": "unknown", "confidence": "0", "signals_used": []}
    return {
        "overall": regime.overall,
        "trend": regime.trend_regime,
        "volatility": regime.volatility_regime,
        "gamma": regime.gamma_regime,
        "iv": regime.iv_regime,
        "confidence": _s(regime.confidence),
        "description": regime.description,
        "signals_used": list(regime.signals_used),
    }


def format_mover(entry: MoverEntry) -> dict[str, Any]:
    """Single mover row (most active / gainer / loser)."""
    return {
        "ticker": entry.ticker,
        "last": _s(entry.last),
        "change_pct": _s(entry.change_pct),
        "volume": entry.volume,
        "category": entry.category,
    }
