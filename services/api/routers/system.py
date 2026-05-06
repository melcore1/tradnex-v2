"""/api/system — status + toggles."""

from __future__ import annotations

from fastapi import APIRouter

from services.api.deps import DB, CurrentUser
from services.api.schemas import SystemStatusResponse, ToggleRequest
from shared.events import emit
from shared.services.runtime_toggles import get_toggles, set_toggle

router = APIRouter()


def _compute_override_reasons(
    *, monitor_paused: bool, open_positions: int,
) -> dict[str, str | None]:
    """Human-readable explanations of why a toggle is forced.

    Currently only the monitor key has logic — when monitor_paused is set
    but there are open positions, the monitor still runs. Phase 8+ will
    likely add scanner ('market closed') and llm ('rate limited')
    overrides."""
    monitor: str | None = None
    if monitor_paused and open_positions > 0:
        plural = "s" if open_positions != 1 else ""
        monitor = (
            f"Monitor forced active — {open_positions} open position{plural}"
        )
    return {"scanner": None, "monitor": monitor, "llm": None}


@router.get("/status", response_model=SystemStatusResponse)
async def status_(db: DB, user: CurrentUser) -> SystemStatusResponse:
    """Aggregated system state: toggles + queue depth + open positions
    + pending approvals + trading_mode + override_reasons."""
    cfg = get_toggles(db)
    queue_depth = int(
        db.execute(
            "SELECT COUNT(*) FROM candidates "
            "WHERE status = 'pending_llm_evaluation'"
        ).fetchone()[0]
    )
    queue_in_flight = int(
        db.execute(
            "SELECT COUNT(*) FROM candidates "
            "WHERE status = 'processing_llm_evaluation'"
        ).fetchone()[0]
    )
    open_positions = int(
        db.execute(
            "SELECT COUNT(*) FROM positions WHERE status = 'open'"
        ).fetchone()[0]
    )
    pending_human = int(
        db.execute(
            "SELECT COUNT(*) FROM candidates "
            "WHERE status = 'pending_human_approval'"
        ).fetchone()[0]
    )
    monitor_paused = bool(cfg.get("monitor_paused", False))
    return SystemStatusResponse(
        paused=bool(cfg.get("paused", False)),
        monitor_paused=monitor_paused,
        llm_enabled=bool(cfg.get("llm_enabled", True)),
        queue_depth=queue_depth,
        queue_in_flight=queue_in_flight,
        open_positions=open_positions,
        pending_human_approvals=pending_human,
        # Phase 7 additions:
        trading_mode="paper",  # hardcoded until Phase 8
        override_reasons=_compute_override_reasons(
            monitor_paused=monitor_paused, open_positions=open_positions,
        ),
    )


@router.post("/toggle", response_model=SystemStatusResponse)
async def toggle(
    payload: ToggleRequest,
    db: DB,
    user: CurrentUser,
) -> SystemStatusResponse:
    """Flip a system toggle. `name` ∈ {paused, monitor_paused, llm_enabled};
    `enabled` is the new value. The keys live in
    strategy_configs.settings_json."""
    # `paused` is a "paused" flag — when caller passes enabled=true they
    # mean "scanner running" so we negate. monitor_paused similarly. For
    # llm_enabled, enabled=true means llm_enabled=true.
    if payload.name == "paused":
        new_value = not payload.enabled  # enabled=true → paused=false
    elif payload.name == "monitor_paused":
        new_value = not payload.enabled
    else:
        new_value = bool(payload.enabled)
    set_toggle(db, payload.name, new_value)
    emit(
        "api",
        "info",
        "system_toggle",
        {
            "user_id": user.id,
            "name": payload.name,
            "enabled": payload.enabled,
            "stored_value": new_value,
        },
    )
    return await status_(db=db, user=user)
