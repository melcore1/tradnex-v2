"""Monitor cycle: iterate open positions, evaluate exit signals, persist."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from services.monitor.persistence import (
    persist_exit_candidate,
    persist_monitor_evaluation,
)
from shared.clients.halt_feed import HaltFeed
from shared.clients.market_data import MarketDataClient
from shared.events import emit
from shared.schemas.core import Position
from shared.services.positions import emit_lifecycle_event, get_open_positions
from shared.strategy.base import ExitCandidate
from shared.strategy.exit_evaluator import evaluate_position_for_exit
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import ExitSignalTrace

SERVICE_NAME = "monitor"


async def _safe_orchestrator_call(candidate_id: int) -> None:
    """Trigger orchestrator with a fresh DB connection. Errors don't
    propagate; the orchestrator's poller catches stragglers."""
    from datetime import UTC, datetime

    from services.orchestrator.process_candidate import process_candidate
    from shared.clients.factory import make_halt_feed
    from shared.config import settings as cfg
    from shared.db import get_connection
    from shared.services.calendar_service import CalendarService
    from shared.strategy.vetoes.base import VetoContext, VetoSettings

    conn = get_connection()
    try:
        halt_feed = make_halt_feed(cfg)
        ctx = VetoContext(
            conn=conn,
            calendar_service=CalendarService(conn),
            halt_feed=halt_feed,
            settings=VetoSettings(),
            current_time_utc=datetime.now(UTC),
        )
        await process_candidate(candidate_id, ctx)
    except Exception as e:
        emit(
            SERVICE_NAME,
            "error",
            "orchestrator_trigger_failed",
            {
                "candidate_id": candidate_id,
                "error": str(e)[:300],
                "error_type": type(e).__name__,
            },
        )
    finally:
        conn.close()


class MonitorCycleResult(BaseModel):
    cycle_id: str
    positions_evaluated: int = 0
    exit_candidates_created: int = 0
    auto_closes_triggered: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


def _new_cycle_id() -> str:
    return uuid.uuid4().hex[:12]


def _exit_signal_type_from_trace(trace: ExitSignalTrace) -> str:
    """Pick one of the canonical ExitSignalType literals from the dominant
    triggered signal. Falls back to 'soft_setup_invalidated'."""
    # Map signal name → exit_signal_type
    mapping = {
        "take_profit": "pnl_based",
        "stop_loss": "pnl_based",
        "trailing_stop": "pnl_based",
        "delta_too_high": "greek_based",
        "delta_too_low": "greek_based",
        "theta_acceleration": "greek_based",
        "vega_exposure": "greek_based",
        "iv_crush": "volatility_based",
        "iv_spike": "volatility_based",
        "dte_critical": "time_based",
        "friday_short_dte": "time_based",
        "underlying_halted": "underlying_based",
        "adverse_gap": "underlying_based",
        "contract_not_found": "underlying_based",
        "setup_invalidated": "soft_setup_invalidated",
    }
    severities = {"auto_close": 4, "urgent": 3, "warning": 2, "info": 1}
    triggered = [s for s in trace.signals if s.triggered]
    if not triggered:
        return "soft_setup_invalidated"
    triggered.sort(key=lambda s: severities.get(s.severity.value, 0), reverse=True)
    top = triggered[0]
    return mapping.get(top.name, "soft_setup_invalidated")


def _build_candidate(position: Position, trace: ExitSignalTrace) -> ExitCandidate:
    return ExitCandidate(
        position_id=trace.position_id,
        ticker=position.ticker,
        exit_signal_type=_exit_signal_type_from_trace(trace),  # type: ignore[arg-type]
        is_auto_close=trace.auto_close_triggered,
        needs_claude=trace.needs_claude,
        auto_close_reason=trace.auto_close_reason,
        triggered_signals=[s.name for s in trace.signals if s.triggered],
        signal_trace=trace,
        pnl_pct=trace.pnl_pct,
        pnl_dollars=trace.pnl_dollars,
        dte_remaining=trace.dte_remaining,
        timestamp=datetime.now(UTC),
    )


async def evaluate_position(
    position: Position,
    client: MarketDataClient,
    halt_feed: HaltFeed,
    conn: sqlite3.Connection,
    settings: ExitSettings,
    cycle_id: str,
) -> tuple[ExitSignalTrace, int | None]:
    """Evaluate one position. Returns (trace, exit_candidate_id_or_None)."""
    if position.id is None:
        raise ValueError("Position must have an id to evaluate")

    trace = await evaluate_position_for_exit(
        position=position,
        client=client,
        halt_feed=halt_feed,
        conn=conn,
        settings=settings,
    )

    # Decide candidate creation
    candidate_id: int | None = None
    if trace.auto_close_triggered:
        candidate = _build_candidate(position, trace)
        candidate_id = await persist_exit_candidate(conn, candidate)
        import asyncio as _asyncio

        _asyncio.create_task(_safe_orchestrator_call(candidate_id))
        await emit_lifecycle_event(
            conn,
            position.id,
            "auto_close_triggered",
            cycle_id=cycle_id,
            payload={
                "exit_candidate_id": candidate_id,
                "reason": trace.auto_close_reason,
                "pnl_pct": str(trace.pnl_pct),
            },
        )
    elif trace.needs_claude:
        candidate = _build_candidate(position, trace)
        candidate_id = await persist_exit_candidate(conn, candidate)
        import asyncio as _asyncio

        _asyncio.create_task(_safe_orchestrator_call(candidate_id))
        await emit_lifecycle_event(
            conn,
            position.id,
            "exit_candidate_created",
            cycle_id=cycle_id,
            payload={
                "exit_candidate_id": candidate_id,
                "urgent_count": trace.urgent_count,
                "warning_count": trace.warning_count,
                "triggered": [s.name for s in trace.signals if s.triggered],
            },
        )

    # Always log the per-cycle evaluation lifecycle event
    await emit_lifecycle_event(
        conn,
        position.id,
        "monitor_evaluated",
        cycle_id=cycle_id,
        payload={
            "pnl_pct": str(trace.pnl_pct),
            "auto_close": trace.auto_close_triggered,
            "needs_claude": trace.needs_claude,
            "exit_candidate_id": candidate_id,
        },
    )

    # Persist the monitor_evaluations row
    halt_status = "halted" if any(
        s.name == "underlying_halted" and s.triggered for s in trace.signals
    ) else "normal"
    underlying_summary = trace.summary
    contract_delta_signal = next(
        (s for s in trace.signals if s.name == "delta_too_high"), None
    )
    current_delta = (
        float(contract_delta_signal.details["delta"])
        if contract_delta_signal is not None and "delta" in contract_delta_signal.details
        else None
    )
    iv_signal = next((s for s in trace.signals if s.name == "iv_crush"), None)
    current_iv = (
        float(iv_signal.details["current_iv"])
        if iv_signal is not None and "current_iv" in iv_signal.details
        else None
    )
    await persist_monitor_evaluation(
        conn,
        trace=trace,
        cycle_id=cycle_id,
        halt_status_at_eval=halt_status,
        underlying_summary=underlying_summary,
        current_delta=current_delta,
        current_iv=current_iv,
        exit_candidate_id=candidate_id,
    )
    return trace, candidate_id


async def run_monitor_cycle(
    client: MarketDataClient,
    halt_feed: HaltFeed,
    conn: sqlite3.Connection,
    settings: ExitSettings,
    cycle_id: str | None = None,
) -> MonitorCycleResult:
    """Run one monitor cycle: fetch open positions, evaluate each."""
    from shared.services.runtime_toggles import get_toggle

    cid = cycle_id or _new_cycle_id()

    # Phase 6: runtime toggle — `monitor_paused` in strategy_configs.settings_json
    # short-circuits the whole cycle. Useful for quick "stop touching live
    # positions" without restarting the service.
    if bool(get_toggle(conn, "monitor_paused", default=False)):
        emit(
            SERVICE_NAME,
            "info",
            "monitor_paused_runtime",
            {"cycle_id": cid},
        )
        return MonitorCycleResult(cycle_id=cid)

    open_positions = await get_open_positions(conn)

    if not open_positions:
        if not settings.monitor_enabled:
            emit(SERVICE_NAME, "info", "monitor_disabled_no_positions", {"cycle_id": cid})
        else:
            emit(SERVICE_NAME, "info", "monitor_no_positions", {"cycle_id": cid})
        return MonitorCycleResult(cycle_id=cid)

    if not settings.monitor_enabled:
        emit(
            SERVICE_NAME,
            "warn",
            "monitor_running_with_flag_off",
            {"cycle_id": cid, "open_count": len(open_positions)},
        )

    positions_evaluated = 0
    exit_candidates_created = 0
    auto_closes_triggered = 0
    errors: list[dict[str, Any]] = []

    for position in open_positions:
        try:
            trace, candidate_id = await evaluate_position(
                position, client, halt_feed, conn, settings, cid
            )
        except Exception as e:
            emit(
                SERVICE_NAME,
                "error",
                "monitor_position_error",
                {
                    "position_id": position.id,
                    "ticker": position.ticker,
                    "cycle_id": cid,
                    "error": str(e)[:300],
                    "error_type": type(e).__name__,
                },
            )
            errors.append(
                {
                    "position_id": position.id,
                    "ticker": position.ticker,
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )
            continue

        positions_evaluated += 1
        if candidate_id is not None:
            if trace.auto_close_triggered:
                auto_closes_triggered += 1
            elif trace.needs_claude:
                exit_candidates_created += 1

    emit(
        SERVICE_NAME,
        "info",
        "monitor_cycle_complete",
        {
            "cycle_id": cid,
            "positions_evaluated": positions_evaluated,
            "exit_candidates_created": exit_candidates_created,
            "auto_closes_triggered": auto_closes_triggered,
            "errors": len(errors),
        },
    )
    return MonitorCycleResult(
        cycle_id=cid,
        positions_evaluated=positions_evaluated,
        exit_candidates_created=exit_candidates_created,
        auto_closes_triggered=auto_closes_triggered,
        errors=errors,
    )
