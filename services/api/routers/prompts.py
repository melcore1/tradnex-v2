"""/api/prompts — Phase 5 prompt versioning surfaced over HTTP."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from services.api.deps import DB, CurrentUser
from services.api.schemas import (
    PromptActivateRequest,
    PromptCreateRequest,
    PromptVersionResponse,
)
from shared.events import emit
from shared.services.prompts import (
    NoActivePromptError,
    PromptVersionNotFoundError,
    activate_prompt_version,
    create_prompt_version,
    get_active_prompt,
    get_prompt_history,
    rollback_to_version,
)

router = APIRouter()


def _to_response(v: object) -> PromptVersionResponse:
    return PromptVersionResponse.model_validate(v, from_attributes=True)


@router.get("/{template_name}/active", response_model=PromptVersionResponse)
async def show_active(
    template_name: str,
    db: DB,
    user: CurrentUser,
) -> PromptVersionResponse:
    """Return the currently-active prompt for a template."""
    if template_name not in ("entry_evaluation", "exit_evaluation"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown template_name '{template_name}'",
        )
    try:
        version = await get_active_prompt(db, template_name)  # type: ignore[arg-type]
    except NoActivePromptError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    return _to_response(version)


@router.get("/{template_name}/history", response_model=list[PromptVersionResponse])
async def history(
    template_name: str,
    db: DB,
    user: CurrentUser,
) -> list[PromptVersionResponse]:
    if template_name not in ("entry_evaluation", "exit_evaluation"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown template_name '{template_name}'",
        )
    versions = await get_prompt_history(db, template_name)  # type: ignore[arg-type]
    return [_to_response(v) for v in versions]


@router.post(
    "",
    response_model=PromptVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_pending(
    payload: PromptCreateRequest,
    db: DB,
    user: CurrentUser,
) -> PromptVersionResponse:
    """Create a new prompt version in 'pending' status. Activate via POST
    /api/prompts/activate to promote it (and demote the current active)."""
    version = await create_prompt_version(
        db,
        template_name=payload.template_name,
        template_text=payload.template_text,
        response_schema=payload.response_schema,
        created_by=user.email,
        notes=payload.notes,
    )
    emit(
        "api",
        "info",
        "prompt_version_created",
        {
            "template": payload.template_name,
            "version_id": version.id,
            "version_number": version.version_number,
            "user_id": user.id,
        },
    )
    return _to_response(version)


@router.post("/activate", response_model=PromptVersionResponse)
async def activate(
    payload: PromptActivateRequest,
    db: DB,
    user: CurrentUser,
) -> PromptVersionResponse:
    """Promote a pending or deprecated version → active. Demotes the
    previously-active row to deprecated. Atomic."""
    try:
        version = await activate_prompt_version(db, payload.version_id)
    except PromptVersionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    emit(
        "api",
        "info",
        "prompt_version_activated",
        {
            "version_id": version.id,
            "template": version.template_name,
            "version_number": version.version_number,
            "user_id": user.id,
        },
    )
    return _to_response(version)


@router.post(
    "/{template_name}/rollback/{version_number}",
    response_model=PromptVersionResponse,
)
async def rollback(
    template_name: str,
    version_number: int,
    db: DB,
    user: CurrentUser,
) -> PromptVersionResponse:
    if template_name not in ("entry_evaluation", "exit_evaluation"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown template_name '{template_name}'",
        )
    try:
        version = await rollback_to_version(
            db, template_name, version_number  # type: ignore[arg-type]
        )
    except PromptVersionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    emit(
        "api",
        "info",
        "prompt_version_rollback",
        {
            "template": template_name,
            "to_version_number": version_number,
            "version_id": version.id,
            "user_id": user.id,
        },
    )
    return _to_response(version)
