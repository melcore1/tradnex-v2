"""Entry hard vetoes V1-V10. Each is a pure async function returning a VetoResult."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from shared.strategy.vetoes.base import (
    OrchestratorCandidate,
    VetoContext,
    VetoResult,
)

ET = ZoneInfo("America/New_York")


async def v1_strategy_paused(
    candidate: OrchestratorCandidate,
    ctx: VetoContext,
) -> VetoResult:
    row = ctx.conn.execute(
        "SELECT settings_json FROM strategy_configs "
        "WHERE name = 'default' AND is_active = 1 LIMIT 1"
    ).fetchone()
    paused = False
    if row is not None and row["settings_json"]:
        cfg = json.loads(row["settings_json"])
        paused = bool(cfg.get("paused", False))
    return VetoResult(
        name="V1_strategy_paused",
        description="Strategy globally paused via config",
        failed=paused,
        failure_reason="Strategy is paused" if paused else None,
        details={"paused": paused},
    )


async def v2_outside_market_window(
    candidate: OrchestratorCandidate,
    ctx: VetoContext,
) -> VetoResult:
    now_et = ctx.current_time_utc.astimezone(ET).time()
    start = datetime.strptime(ctx.market_window_start_et, "%H:%M").time()
    end = datetime.strptime(ctx.market_window_end_et, "%H:%M").time()
    inside = start <= now_et <= end
    return VetoResult(
        name="V2_outside_market_window",
        description=f"Trading window {ctx.market_window_start_et}-{ctx.market_window_end_et} ET",
        failed=not inside,
        failure_reason=(
            None
            if inside
            else f"Current ET time {now_et.isoformat(timespec='minutes')} outside window"
        ),
        details={
            "now_et": now_et.isoformat(timespec="minutes"),
            "start": ctx.market_window_start_et,
            "end": ctx.market_window_end_et,
        },
    )


def _week_start_ts(now_utc: datetime) -> float:
    """Monday 00:00 UTC of the current week."""
    weekday = now_utc.weekday()
    monday = now_utc - timedelta(days=weekday)
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.timestamp()


async def v3_weekly_trade_cap(
    candidate: OrchestratorCandidate,
    ctx: VetoContext,
) -> VetoResult:
    week_start = _week_start_ts(ctx.current_time_utc)
    row = ctx.conn.execute(
        "SELECT COUNT(*) FROM candidates "
        "WHERE candidate_kind = 'entry' "
        "AND status IN ('approved', 'placed') "
        "AND created_ts >= ?",
        (week_start,),
    ).fetchone()
    count = int(row[0]) if row is not None else 0
    cap = ctx.settings.weekly_trade_cap
    failed = count >= cap
    return VetoResult(
        name="V3_weekly_trade_cap",
        description=f"Weekly trade cap of {cap} approved/placed entries",
        failed=failed,
        failure_reason=(
            f"Already {count} approved/placed this week (cap {cap})" if failed else None
        ),
        details={"count": count, "cap": cap, "week_start_ts": week_start},
    )


async def v4_weekly_loss_circuit_breaker(
    candidate: OrchestratorCandidate,
    ctx: VetoContext,
) -> VetoResult:
    week_start = _week_start_ts(ctx.current_time_utc)
    row = ctx.conn.execute(
        "SELECT COALESCE(SUM(pnl), 0) FROM positions "
        "WHERE status = 'closed' AND exit_ts >= ?",
        (week_start,),
    ).fetchone()
    weekly_pnl = Decimal(str(row[0])) if row is not None else Decimal("0")
    notional = ctx.settings.account_notional_for_pct
    pnl_pct = (weekly_pnl / notional * Decimal("100")) if notional > 0 else Decimal("0")
    threshold = ctx.settings.weekly_loss_circuit_breaker_pct
    failed = pnl_pct <= threshold
    return VetoResult(
        name="V4_weekly_loss_circuit_breaker",
        description=f"Weekly P&L circuit breaker at {threshold}% of notional",
        failed=failed,
        failure_reason=(
            f"Weekly P&L {pnl_pct}% <= breaker {threshold}%" if failed else None
        ),
        details={
            "weekly_pnl_dollars": str(weekly_pnl),
            "weekly_pnl_pct": str(pnl_pct),
            "threshold_pct": str(threshold),
            "notional": str(notional),
        },
    )


async def v5_concurrent_positions_cap(
    candidate: OrchestratorCandidate,
    ctx: VetoContext,
) -> VetoResult:
    row = ctx.conn.execute(
        "SELECT COUNT(*) FROM positions WHERE status = 'open'"
    ).fetchone()
    open_count = int(row[0]) if row is not None else 0
    cap = ctx.settings.concurrent_positions_cap
    failed = open_count >= cap
    return VetoResult(
        name="V5_concurrent_positions_cap",
        description=f"Maximum {cap} concurrent open positions",
        failed=failed,
        failure_reason=(
            f"Already {open_count} open positions (cap {cap})" if failed else None
        ),
        details={"open_count": open_count, "cap": cap},
    )


async def v6_earnings_blackout(
    candidate: OrchestratorCandidate,
    ctx: VetoContext,
) -> VetoResult:
    next_earn = await ctx.calendar_service.get_next_earnings(candidate.ticker)
    days_before = ctx.settings.earnings_blackout_days_before
    days_after = ctx.settings.earnings_blackout_days_after
    failed = False
    reason: str | None = None
    details: dict[str, object] = {
        "ticker": candidate.ticker,
        "days_before": days_before,
        "days_after": days_after,
    }
    if next_earn is not None:
        delta = next_earn.event_datetime_utc - ctx.current_time_utc
        days_until = delta.total_seconds() / 86400
        details["next_earnings_utc"] = next_earn.event_datetime_utc.isoformat()
        details["days_until"] = round(days_until, 2)
        if -days_after <= days_until <= days_before:
            failed = True
            reason = (
                f"{candidate.ticker} earnings in {round(days_until, 2)} days "
                f"(blackout -{days_after}…+{days_before})"
            )
    return VetoResult(
        name="V6_earnings_blackout",
        description=(
            f"No entries within {days_before} days before / "
            f"{days_after} days after earnings"
        ),
        failed=failed,
        failure_reason=reason,
        details=details,
    )


async def v7_macro_event_window(
    candidate: OrchestratorCandidate,
    ctx: VetoContext,
) -> VetoResult:
    hours = ctx.settings.macro_event_blackout_hours
    has_high = await ctx.calendar_service.has_high_impact_within(
        hours, event_type="economic"
    )
    return VetoResult(
        name="V7_macro_event_window",
        description=f"No entries within {hours}h of high-impact macro event",
        failed=has_high,
        failure_reason=(
            f"High-impact macro event within next {hours}h" if has_high else None
        ),
        details={
            "hours_window": hours,
            "high_impact_present": has_high,
            "min_impact": ctx.settings.macro_event_min_impact,
        },
    )


async def v8_active_halt(
    candidate: OrchestratorCandidate,
    ctx: VetoContext,
) -> VetoResult:
    halted = await ctx.halt_feed.is_halted(candidate.ticker)
    return VetoResult(
        name="V8_active_halt",
        description="Underlying not halted at evaluation",
        failed=halted,
        failure_reason=(f"{candidate.ticker} is halted" if halted else None),
        details={"ticker": candidate.ticker, "halted": halted},
    )


async def v9_vix_spike(
    candidate: OrchestratorCandidate,
    ctx: VetoContext,
) -> VetoResult:
    if not ctx.settings.vix_veto_enabled:
        return VetoResult(
            name="V9_vix_spike",
            description="VIX spike check (deferred — not enabled in v1)",
            failed=False,
            failure_reason=None,
            details={"deferred": True, "reason": "vix_veto_enabled=False"},
        )
    return VetoResult(
        name="V9_vix_spike",
        description="VIX spike check",
        failed=False,
        failure_reason=None,
        details={
            "deferred": True,
            "note": "VIX quote source not wired; check returns pass",
        },
    )


async def v10_duplicate_candidate(
    candidate: OrchestratorCandidate,
    ctx: VetoContext,
) -> VetoResult:
    minutes = ctx.settings.duplicate_window_minutes
    cutoff = ctx.current_time_utc.timestamp() - minutes * 60
    row = ctx.conn.execute(
        "SELECT id FROM candidates "
        "WHERE candidate_kind = 'entry' "
        "AND ticker = ? "
        "AND direction = ? "
        "AND created_ts >= ? "
        "AND id != ? "
        "LIMIT 1",
        (candidate.ticker, candidate.direction, cutoff, candidate.id),
    ).fetchone()
    duplicate = row is not None
    return VetoResult(
        name="V10_duplicate_candidate",
        description=f"No duplicate (ticker, direction) in last {minutes} min",
        failed=duplicate,
        failure_reason=(
            f"Duplicate candidate for {candidate.ticker} {candidate.direction} "
            f"within last {minutes} min"
            if duplicate
            else None
        ),
        details={
            "ticker": candidate.ticker,
            "direction": candidate.direction,
            "window_minutes": minutes,
            "duplicate_id": row["id"] if duplicate else None,
        },
    )


ENTRY_VETOES = [
    v1_strategy_paused,
    v2_outside_market_window,
    v3_weekly_trade_cap,
    v4_weekly_loss_circuit_breaker,
    v5_concurrent_positions_cap,
    v6_earnings_blackout,
    v7_macro_event_window,
    v8_active_halt,
    v9_vix_spike,
    v10_duplicate_candidate,
]
