"""Aggregate every exit signal into one ExitSignalTrace per position."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal

from shared.analytics.full_analysis import compute_full_analysis
from shared.analytics.options.full_options_analysis import (
    FullOptionsAnalysis,
    compute_options_analysis,
)
from shared.clients.halt_feed import Halt, HaltFeed
from shared.clients.market_data import MarketDataClient
from shared.events import emit
from shared.schemas.core import Position
from shared.services.positions import get_position_high_water_mark
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals import (
    ExitSignal,
    ExitSignalCategory,
    ExitSignalSeverity,
    ExitSignalTrace,
    signal_adverse_gap,
    signal_charm_acceleration,
    signal_delta_too_high,
    signal_delta_too_low,
    signal_dte_critical,
    signal_friday_position_short_dte,
    signal_iv_crush,
    signal_iv_spike,
    signal_setup_invalidated,
    signal_stop_loss,
    signal_take_profit,
    signal_theta_acceleration,
    signal_trailing_stop,
    signal_underlying_halted,
    signal_vega_exposure,
)


async def _resolve_halt_for(
    halt_feed: HaltFeed,
    ticker: str,
) -> tuple[bool, Halt | None]:
    is_halted = await halt_feed.is_halted(ticker)
    if not is_halted:
        return False, None
    actives = await halt_feed.get_active_halts()
    matching = next((h for h in actives if h.ticker.upper() == ticker.upper()), None)
    return True, matching


async def evaluate_position_for_exit(
    position: Position,
    client: MarketDataClient,
    halt_feed: HaltFeed,
    conn: sqlite3.Connection,
    settings: ExitSettings,
) -> ExitSignalTrace:
    """Run every exit signal on a position and aggregate severity counts."""
    if position.id is None:
        raise ValueError("Position must have an id to evaluate")

    quote = await client.get_quote(position.ticker)
    chain = await client.get_options_chain(position.ticker)
    contract = next(
        (c for c in chain.contracts if c.symbol == position.contract_symbol), None
    )

    if contract is None:
        # Special-case: contract no longer in chain (likely expired).
        emit(
            "monitor",
            "warn",
            "monitor_contract_not_found",
            {"position_id": position.id, "contract_symbol": position.contract_symbol},
        )
        signal = ExitSignal(
            name="contract_not_found",
            category=ExitSignalCategory.UNDERLYING,
            severity=ExitSignalSeverity.URGENT,
            triggered=True,
            description=(
                f"Contract {position.contract_symbol} no longer in chain — "
                "possibly expired"
            ),
            details={"contract_symbol": position.contract_symbol},
            threshold_used={},
        )
        return ExitSignalTrace(
            position_id=position.id,
            timestamp=datetime.now(UTC),
            ticker=position.ticker,
            contract_symbol=position.contract_symbol,
            entry_price=position.entry_price,
            current_price=Decimal("0"),
            pnl_pct=Decimal("0"),
            pnl_dollars=Decimal("0"),
            quantity=position.quantity,
            dte_remaining=0,
            signals=[signal],
            auto_close_triggered=False,
            auto_close_reason=None,
            urgent_count=1,
            warning_count=0,
            info_count=0,
            needs_claude=True,
        )

    is_halted, halt_info = await _resolve_halt_for(halt_feed, position.ticker)

    # Pull historical bars for the setup-invalidated signal
    bars_daily = await client.get_bars(position.ticker, "1d", limit=300)
    bars_5m = await client.get_bars(position.ticker, "5m", limit=200)

    options_analysis: FullOptionsAnalysis | None
    try:
        options_analysis = compute_options_analysis(chain, conn)
    except Exception as e:
        emit(
            "monitor",
            "warn",
            "monitor_options_analysis_failed",
            {"position_id": position.id, "error": str(e)[:200]},
        )
        options_analysis = None

    full_analysis = await compute_full_analysis(
        position.ticker, bars_daily, "1d", options_analysis=options_analysis
    )

    high_water_mark_pct = await get_position_high_water_mark(conn, position.id)
    now_dt = datetime.now(UTC)

    signals: list[ExitSignal] = [
        signal_take_profit(position, contract.mid, settings),
        signal_stop_loss(position, contract.mid, settings),
        signal_trailing_stop(position, contract.mid, high_water_mark_pct, settings),
        signal_delta_too_high(position, contract, settings),
        signal_delta_too_low(position, contract, settings),
        signal_theta_acceleration(position, contract, settings),
        signal_vega_exposure(position, contract, settings),
        signal_charm_acceleration(position, contract, settings),
        signal_iv_crush(position, contract.iv, position.entry_iv, settings),
        signal_iv_spike(position, contract.iv, position.entry_iv, settings),
        signal_dte_critical(position, contract, now_dt, settings),
        signal_friday_position_short_dte(position, contract, now_dt, settings),
        signal_underlying_halted(position, is_halted, halt_info, settings),
        signal_adverse_gap(position, quote, settings),
        signal_setup_invalidated(position, full_analysis, bars_5m, settings),
    ]

    auto_close = next(
        (s for s in signals if s.severity == ExitSignalSeverity.AUTO_CLOSE and s.triggered),
        None,
    )
    urgent_count = sum(
        1 for s in signals if s.severity == ExitSignalSeverity.URGENT and s.triggered
    )
    warning_count = sum(
        1 for s in signals if s.severity == ExitSignalSeverity.WARNING and s.triggered
    )
    info_count = sum(
        1 for s in signals if s.severity == ExitSignalSeverity.INFO and s.triggered
    )

    # P&L snapshot
    pnl_pct = (
        (contract.mid - position.entry_price) / position.entry_price * Decimal("100")
        if position.entry_price > 0
        else Decimal("0")
    )
    pnl_dollars = (
        (contract.mid - position.entry_price) * Decimal("100") * Decimal(position.quantity)
    )

    auto_close_triggered = auto_close is not None
    needs_claude = (not auto_close_triggered) and (urgent_count > 0 or warning_count > 0)

    return ExitSignalTrace(
        position_id=position.id,
        timestamp=now_dt,
        ticker=position.ticker,
        contract_symbol=position.contract_symbol,
        entry_price=position.entry_price,
        current_price=contract.mid,
        pnl_pct=pnl_pct,
        pnl_dollars=pnl_dollars,
        quantity=position.quantity,
        dte_remaining=contract.dte,
        signals=signals,
        auto_close_triggered=auto_close_triggered,
        auto_close_reason=auto_close.description if auto_close is not None else None,
        urgent_count=urgent_count,
        warning_count=warning_count,
        info_count=info_count,
        needs_claude=needs_claude,
    )
