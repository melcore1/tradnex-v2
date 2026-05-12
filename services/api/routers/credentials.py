"""/api/credentials — encrypted credential metadata management.

Phase 8a. The frontend sends provider keys (Alpaca, Finnhub, Exa, ...) here
to be encrypted with the master `ENCRYPTION_KEY` and stored in the
`credentials` table. Reads return metadata only — actual secret values
never leave the database via this API.

Endpoints
---------
GET    /api/credentials                  list metadata
GET    /api/credentials/{type}           single metadata
PUT    /api/credentials/{type}           upsert (write-only over the wire)
DELETE /api/credentials/{type}           remove
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from services.api.deps import DB, CurrentUser, Encryption
from services.api.schemas import (
    CredentialRecordResponse,
    CredentialTypeLiteral,
    UpsertCredentialRequest,
)
from shared.services.credentials import (
    VALID_CREDENTIAL_TYPES,
    CredentialType,
    delete_credential,
    get_credential_record,
    list_credential_records,
    upsert_credential,
)

router = APIRouter()


def _ensure_valid_type(credential_type: str) -> CredentialType:
    if credential_type not in VALID_CREDENTIAL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown credential_type '{credential_type}'. Valid: "
                f"{sorted(VALID_CREDENTIAL_TYPES)}"
            ),
        )
    return credential_type


def _record_to_response(record: object) -> CredentialRecordResponse:
    # CredentialRecord uses identical field names; passthrough via model_dump.
    return CredentialRecordResponse.model_validate(
        record.model_dump() if hasattr(record, "model_dump") else record
    )


@router.get("", response_model=list[CredentialRecordResponse])
async def list_credentials(
    db: DB,
    user: CurrentUser,
    _: Encryption,  # ensures the key is valid before any read attempts
) -> list[CredentialRecordResponse]:
    """All configured credentials, metadata only. Always returns a list
    (empty when nothing is configured)."""
    records = list_credential_records(db)
    return [_record_to_response(r) for r in records]


@router.get(
    "/{credential_type}",
    response_model=CredentialRecordResponse,
)
async def get_credential(
    credential_type: CredentialTypeLiteral,
    db: DB,
    user: CurrentUser,
    _: Encryption,
) -> CredentialRecordResponse:
    """Single credential metadata. 404 when not configured."""
    typed = _ensure_valid_type(credential_type)
    record = get_credential_record(db, typed)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential '{credential_type}' not configured",
        )
    return _record_to_response(record)


@router.put(
    "/{credential_type}",
    response_model=CredentialRecordResponse,
)
async def upsert_credential_endpoint(
    credential_type: CredentialTypeLiteral,
    payload: UpsertCredentialRequest,
    db: DB,
    user: CurrentUser,
    encryption: Encryption,
) -> CredentialRecordResponse:
    """Insert or replace a credential. Body's `secrets` dict is encrypted
    before write. The response NEVER echoes the secrets back."""
    typed = _ensure_valid_type(credential_type)
    record = upsert_credential(
        db,
        encryption,
        typed,
        secrets=payload.secrets,
        notes=payload.notes,
        user_id=user.id,
    )
    return _record_to_response(record)


@router.delete(
    "/{credential_type}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_credential_endpoint(
    credential_type: CredentialTypeLiteral,
    db: DB,
    user: CurrentUser,
    _: Encryption,
) -> None:
    """Remove the credential row. 404 when not configured (idempotent
    callers should check `GET` first or accept 404)."""
    typed = _ensure_valid_type(credential_type)
    deleted = delete_credential(db, typed, user_id=user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential '{credential_type}' not configured",
        )
