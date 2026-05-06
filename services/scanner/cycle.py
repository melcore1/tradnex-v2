"""Scan-cycle loop: iterate the watchlist, evaluate the strategy per ticker."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from shared.analytics.full_analysis import compute_full_analysis
from shared.analytics.options.full_options_analysis import (
    FullOptionsAnalysis,
    compute_options_analysis,
)
from shared.clients.market_data import MarketDataClient
from shared.events import emit
from shared.services.watchlist import get_active_watchlist
from shared.strategy.base import EntryCandidate, RuleTrace, Strategy
from shared.strategy.shortlist import build_shortlist

SERVICE_NAME = "scanner"


async def _safe_orchestrator_call(candidate_id: int) -> None:
    """Build a fresh VetoContext (with its own DB connection) and run the
    orchestrator on the new candidate. Errors here don't propagate — the
    candidate is left in `pending` so the orchestrator poller can retry."""
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


class TickerEvaluationResult(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    ticker: str
    rule_trace: RuleTrace
    candidate: EntryCandidate | None
    candidate_id: int | None = None


class ScanCycleResult(BaseModel):
    cycle_id: str
    tickers_evaluated: int = 0
    candidates_fired: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


def _new_cycle_id() -> str:
    return uuid.uuid4().hex[:12]


async def evaluate_ticker(
    ticker: str,
    client: MarketDataClient,
    conn: sqlite3.Connection,
    strategy: Strategy,
    overrides: dict[str, Any],
    cycle_id: str,
) -> TickerEvaluationResult:
    """Evaluate one ticker. Always returns a trace; candidate may be None."""
    bars_5m = await client.get_bars(ticker, "5m", limit=200)
    bars_daily = await client.get_bars(ticker, "1d", limit=300)
    chain = await client.get_options_chain(ticker, min_dte=3, max_dte=14)

    options_analysis: FullOptionsAnalysis | None
    try:
        options_analysis = compute_options_analysis(chain, conn)
    except Exception as e:
        emit(
            SERVICE_NAME,
            "warn",
            "options_analysis_failed",
            {"ticker": ticker, "cycle_id": cycle_id, "error": str(e)[:200]},
        )
        options_analysis = None

    full_analysis = await compute_full_analysis(
        ticker,
        bars_daily,
        timeframe="1d",
        options_analysis=options_analysis,
    )
    if full_analysis.regime is None:
        # compute_full_analysis always populates regime; defensive guard for type checker
        from shared.analytics.regime import classify_regime

        regime = classify_regime(full_analysis, options_analysis, bars_daily)
    else:
        regime = full_analysis.regime

    rule_trace, candidate = await strategy.evaluate_entry(
        ticker=ticker,
        bars_5m=bars_5m,
        bars_daily=bars_daily,
        full_analysis=full_analysis,
        options_analysis=options_analysis,
        regime=regime,
        overrides=overrides,
    )

    if candidate is not None:
        strat_settings = getattr(strategy, "settings", None)
        params = getattr(strat_settings, "shortlist_params", None)
        candidate.shortlist = build_shortlist(
            chain,
            direction=candidate.direction,
            params=params,
        )
        if not candidate.shortlist:
            emit(
                SERVICE_NAME,
                "info",
                "shortlist_empty_no_fire",
                {"ticker": ticker, "cycle_id": cycle_id},
            )
            rule_trace.fired = False
            rule_trace.fire_decision_reason = (
                "shortlist_empty_insufficient_dte_diversity"
            )
            candidate = None
        else:
            # Phase 5: when the LLM bypass is on, the scanner pre-picks the
            # contract deterministically here — no Claude call later. The
            # evaluator's fallback path will still run and persist a row
            # (with fallback_reason='llm_disabled') for full audit.
            evaluator_cfg = getattr(strat_settings, "evaluator", None)
            if (
                evaluator_cfg is not None
                and not evaluator_cfg.llm_enabled
            ):
                from shared.strategy.long_options_momentum import (
                    select_default_contract,
                )

                pick = select_default_contract(
                    candidate.shortlist,
                    (
                        evaluator_cfg.delta_target_range_low,
                        evaluator_cfg.delta_target_range_high,
                    ),
                )
                if pick is not None:
                    candidate.selected_contract = pick

    # Persist
    from services.scanner.persistence import persist_candidate, persist_evaluation

    candidate_id: int | None = None
    if candidate is not None:
        candidate_id = await persist_candidate(conn, candidate)
        # Trigger orchestrator immediately. Fire-and-forget so the cycle
        # doesn't block; on failure the candidate stays in 'pending' and
        # the orchestrator's backup poller catches it.
        import asyncio as _asyncio

        _asyncio.create_task(_safe_orchestrator_call(candidate_id))

    await persist_evaluation(
        conn,
        ticker=ticker,
        cycle_id=cycle_id,
        rule_trace=rule_trace,
        full_analysis=full_analysis,
        options_analysis=options_analysis,
        regime=regime,
        candidate_id=candidate_id,
    )

    return TickerEvaluationResult(
        ticker=ticker,
        rule_trace=rule_trace,
        candidate=candidate,
        candidate_id=candidate_id,
    )


async def run_scan_cycle(
    client: MarketDataClient,
    conn: sqlite3.Connection,
    strategy: Strategy,
    cycle_id: str | None = None,
) -> ScanCycleResult:
    """Run one full cycle: fetch watchlist, evaluate each ticker."""
    cid = cycle_id or _new_cycle_id()
    watchlist = await get_active_watchlist(conn)

    if not watchlist.tickers:
        emit(
            SERVICE_NAME,
            "info",
            "scanner_skipped_empty_watchlist",
            {"cycle_id": cid},
        )
        return ScanCycleResult(cycle_id=cid)

    candidates_fired = 0
    tickers_evaluated = 0
    errors: list[dict[str, Any]] = []

    for ticker in watchlist.tickers:
        ticker_overrides = watchlist.per_ticker_overrides.get(ticker, {})
        try:
            result = await evaluate_ticker(
                ticker=ticker,
                client=client,
                conn=conn,
                strategy=strategy,
                overrides=ticker_overrides,
                cycle_id=cid,
            )
        except Exception as e:
            emit(
                SERVICE_NAME,
                "error",
                "scanner_ticker_error",
                {
                    "ticker": ticker,
                    "cycle_id": cid,
                    "error": str(e)[:300],
                    "error_type": type(e).__name__,
                },
            )
            errors.append({"ticker": ticker, "error": str(e), "error_type": type(e).__name__})
            continue

        tickers_evaluated += 1
        if result.candidate is not None:
            candidates_fired += 1

    emit(
        SERVICE_NAME,
        "info",
        "scan_cycle_complete",
        {
            "cycle_id": cid,
            "tickers_evaluated": tickers_evaluated,
            "candidates_fired": candidates_fired,
            "errors": len(errors),
        },
    )

    return ScanCycleResult(
        cycle_id=cid,
        tickers_evaluated=tickers_evaluated,
        candidates_fired=candidates_fired,
        errors=errors,
    )
