"""/api/settings — strategy_configs.settings_json get/update."""

from __future__ import annotations

from fastapi import APIRouter

from services.api.deps import DB, CurrentUser
from services.api.schemas import SettingsResponse, SettingsUpdateRequest
from shared.events import emit
from shared.services.runtime_toggles import get_toggles, set_toggles

router = APIRouter()


@router.get("", response_model=SettingsResponse)
async def get_settings(db: DB, user: CurrentUser) -> SettingsResponse:
    """Return the active strategy_configs.settings_json contents."""
    return SettingsResponse(settings_json=get_toggles(db))


@router.patch("", response_model=SettingsResponse)
async def update_settings(
    payload: SettingsUpdateRequest,
    db: DB,
    user: CurrentUser,
) -> SettingsResponse:
    """Merge `updates` into the existing settings_json. Atomic."""
    merged = set_toggles(db, payload.updates)
    emit(
        "api",
        "info",
        "settings_updated",
        {"user_id": user.id, "keys": list(payload.updates.keys())},
    )
    return SettingsResponse(settings_json=merged)
