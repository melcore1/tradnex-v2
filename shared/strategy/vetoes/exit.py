"""Exit hard vetoes V_E1, V_E2 — light operational checks."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from shared.strategy.vetoes.base import (
    OrchestratorCandidate,
    VetoContext,
    VetoResult,
)

ET = ZoneInfo("America/New_York")


async def v_e1_outside_close_window(
    candidate: OrchestratorCandidate,
    ctx: VetoContext,
) -> VetoResult:
    now_et = ctx.current_time_utc.astimezone(ET).time()
    cutoff = datetime.strptime(ctx.settings.exit_window_cutoff_et, "%H:%M").time()
    after_cutoff = now_et > cutoff
    return VetoResult(
        name="V_E1_outside_close_window",
        description=f"No new exit candidates after {ctx.settings.exit_window_cutoff_et} ET",
        failed=after_cutoff,
        failure_reason=(
            f"Current ET time {now_et.isoformat(timespec='minutes')} after "
            f"{ctx.settings.exit_window_cutoff_et} cutoff"
            if after_cutoff
            else None
        ),
        details={
            "now_et": now_et.isoformat(timespec="minutes"),
            "cutoff": ctx.settings.exit_window_cutoff_et,
        },
    )


async def v_e2_duplicate_exit(
    candidate: OrchestratorCandidate,
    ctx: VetoContext,
) -> VetoResult:
    if candidate.position_id is None:
        return VetoResult(
            name="V_E2_duplicate_exit",
            description="No-op when position_id missing",
            failed=False,
            details={"position_id": None},
        )
    minutes = ctx.settings.exit_duplicate_window_minutes
    cutoff = ctx.current_time_utc.timestamp() - minutes * 60
    row = ctx.conn.execute(
        "SELECT id FROM candidates "
        "WHERE candidate_kind = 'exit' "
        "AND position_id = ? "
        "AND created_ts >= ? "
        "AND id != ? "
        "LIMIT 1",
        (candidate.position_id, cutoff, candidate.id),
    ).fetchone()
    duplicate = row is not None
    return VetoResult(
        name="V_E2_duplicate_exit",
        description=f"No duplicate exit for same position within {minutes} min",
        failed=duplicate,
        failure_reason=(
            f"Duplicate exit for position {candidate.position_id} within last {minutes} min"
            if duplicate
            else None
        ),
        details={
            "position_id": candidate.position_id,
            "window_minutes": minutes,
            "duplicate_id": row["id"] if duplicate else None,
        },
    )


EXIT_VETOES = [v_e1_outside_close_window, v_e2_duplicate_exit]
