"""Credentials service: encrypted secret storage with metadata-only public reads.

Phase 8a introduces this module to remove credentials from `.env` (except the
master `ENCRYPTION_KEY`). The frontend reads `CredentialRecord` (no secrets,
just "is configured + when") via `list_credential_records` and writes new
secrets via `upsert_credential`. Only internal callers (factories) ever pull
the actual decrypted values via `get_credential_secrets`.

Cache: per-process, invalidated on upsert/delete. Each long-running service
holds one EncryptionService instance and shares this module's cache. The
cache key includes `credential_type`, so updating one type doesn't blow away
others.

Events emitted:
    credentials_updated  → {credential_type, user_id|None}
    credentials_deleted  → {credential_type, user_id|None}
"""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from shared.events import emit
from shared.services.encryption import EncryptionService

CredentialType = Literal[
    "alpaca_paper",
    "alpaca_live",
    "schwab_oauth",
    "finnhub",
    "exa",
]

VALID_CREDENTIAL_TYPES: tuple[CredentialType, ...] = (
    "alpaca_paper",
    "alpaca_live",
    "schwab_oauth",
    "finnhub",
    "exa",
)


class CredentialNotFoundError(LookupError):
    """No row exists for the requested credential_type."""


class CredentialRecord(BaseModel):
    """Public-facing credential metadata. NEVER contains actual secrets."""

    credential_type: CredentialType
    is_configured: bool
    expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    last_used_ts: datetime | None = None
    created_ts: datetime
    updated_ts: datetime
    notes: str | None = None


# Process-local secrets cache. Keyed by credential_type. Reset on
# upsert/delete (and on encryption-key rotation, implicitly, since the
# decrypt would fail). Bounded size: at most len(VALID_CREDENTIAL_TYPES).
_secrets_cache: dict[str, dict[str, Any]] = {}


def _to_iso(ts: float | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=UTC)


def _row_to_record(row: sqlite3.Row) -> CredentialRecord:
    return CredentialRecord(
        credential_type=row["credential_type"],
        is_configured=True,
        expires_at=_to_iso(row["expires_at"]),
        refresh_token_expires_at=_to_iso(row["refresh_token_expires_at"]),
        last_used_ts=_to_iso(row["last_used_ts"]),
        created_ts=_to_iso(row["created_ts"]) or datetime.now(UTC),
        updated_ts=_to_iso(row["updated_ts"]) or datetime.now(UTC),
        notes=row["notes"],
    )


def list_credential_records(conn: sqlite3.Connection) -> list[CredentialRecord]:
    """All configured credentials with metadata only. No secrets in response."""
    rows = conn.execute(
        "SELECT credential_type, expires_at, refresh_token_expires_at, "
        "last_used_ts, created_ts, updated_ts, notes "
        "FROM credentials ORDER BY credential_type"
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_credential_record(
    conn: sqlite3.Connection, credential_type: CredentialType
) -> CredentialRecord | None:
    """Metadata for a single credential type, or None when not configured."""
    row = conn.execute(
        "SELECT credential_type, expires_at, refresh_token_expires_at, "
        "last_used_ts, created_ts, updated_ts, notes "
        "FROM credentials WHERE credential_type = ?",
        (credential_type,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def get_credential_secrets(
    conn: sqlite3.Connection,
    encryption: EncryptionService,
    credential_type: CredentialType,
    *,
    use_cache: bool = True,
) -> dict[str, Any] | None:
    """Decrypt and return the secret values. Internal callers only.

    Returns None when no credential is configured for `credential_type`.
    Updates `last_used_ts` so the UI can show recency.
    """
    if use_cache and credential_type in _secrets_cache:
        return _secrets_cache[credential_type]

    row = conn.execute(
        "SELECT encrypted_data FROM credentials WHERE credential_type = ?",
        (credential_type,),
    ).fetchone()
    if row is None:
        return None

    secrets = encryption.decrypt(row["encrypted_data"])
    _secrets_cache[credential_type] = secrets

    # Best-effort: bump last_used_ts. Don't block readers on the write.
    try:
        conn.execute(
            "UPDATE credentials SET last_used_ts = ? WHERE credential_type = ?",
            (time.time(), credential_type),
        )
        conn.commit()
    except sqlite3.OperationalError:
        # Read-only connection or DB locked; skip without raising.
        pass

    return secrets


def upsert_credential(
    conn: sqlite3.Connection,
    encryption: EncryptionService,
    credential_type: CredentialType,
    secrets: dict[str, Any],
    *,
    notes: str | None = None,
    user_id: int | None = None,
    expires_at: datetime | None = None,
    refresh_token_expires_at: datetime | None = None,
) -> CredentialRecord:
    """Insert or replace a credential row. Encrypts before persisting and
    invalidates the in-process cache.

    Emits `credentials_updated` with {credential_type, user_id}.
    """
    if credential_type not in VALID_CREDENTIAL_TYPES:
        raise ValueError(f"Unknown credential_type: {credential_type}")
    if not isinstance(secrets, dict) or not secrets:
        raise ValueError(
            "`secrets` must be a non-empty dict of provider-specific values."
        )

    encrypted = encryption.encrypt(secrets)
    now = time.time()
    expires_ts = expires_at.timestamp() if expires_at else None
    refresh_expires_ts = (
        refresh_token_expires_at.timestamp() if refresh_token_expires_at else None
    )

    existing = conn.execute(
        "SELECT id, created_ts FROM credentials WHERE credential_type = ?",
        (credential_type,),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO credentials ("
            "credential_type, encrypted_data, expires_at, "
            "refresh_token_expires_at, created_ts, updated_ts, "
            "created_by_user_id, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                credential_type,
                encrypted,
                expires_ts,
                refresh_expires_ts,
                now,
                now,
                user_id,
                notes,
            ),
        )
    else:
        conn.execute(
            "UPDATE credentials SET encrypted_data = ?, expires_at = ?, "
            "refresh_token_expires_at = ?, updated_ts = ?, notes = ? "
            "WHERE credential_type = ?",
            (
                encrypted,
                expires_ts,
                refresh_expires_ts,
                now,
                notes,
                credential_type,
            ),
        )
    conn.commit()

    # Bust the cache for this type
    _secrets_cache.pop(credential_type, None)

    emit(
        "credentials",
        "info",
        "credentials_updated",
        {"credential_type": credential_type, "user_id": user_id},
    )

    record = get_credential_record(conn, credential_type)
    assert record is not None  # we just upserted
    return record


def delete_credential(
    conn: sqlite3.Connection,
    credential_type: CredentialType,
    *,
    user_id: int | None = None,
) -> bool:
    """Remove the row. Returns True if a row was deleted, False if missing.

    Emits `credentials_deleted`.
    """
    cur = conn.execute(
        "DELETE FROM credentials WHERE credential_type = ?",
        (credential_type,),
    )
    conn.commit()
    _secrets_cache.pop(credential_type, None)

    if cur.rowcount == 0:
        return False

    emit(
        "credentials",
        "info",
        "credentials_deleted",
        {"credential_type": credential_type, "user_id": user_id},
    )
    return True


def clear_cache() -> None:
    """Drop all cached decrypted secrets. Call after key rotation."""
    _secrets_cache.clear()


# ---- Env → DB migration ----------------------------------------------------
#
# Phase 8a moves provider keys out of `.env` and into the encrypted store.
# On first startup, any keys still present in env are imported into the DB
# (encrypted) and an `env_credential_migrated` event is emitted. After this
# point, env values are ignored — factories prefer DB and only fall back to
# env as a last-resort safety net. Re-running the migration is a no-op when
# DB rows already exist for the migrated types.
#
# Schwab client_id/client_secret are NOT migrated: they're app-level OAuth
# config, not per-user secrets, and stay in env. The `schwab_oauth`
# credential type is reserved for the user's access/refresh tokens once
# the OAuth flow lands in Phase 8c.

# Maps env var name → credential type → secrets-dict shape.
_ENV_MIGRATIONS: tuple[tuple[str, CredentialType, str], ...] = (
    ("FINNHUB_API_KEY", "finnhub", "api_key"),
    ("EXA_API_KEY", "exa", "api_key"),
)


def migrate_env_credentials(
    conn: sqlite3.Connection,
    encryption: EncryptionService,
    *,
    env: dict[str, str | None] | None = None,
) -> list[CredentialType]:
    """Migrate env-resident credentials to the encrypted DB store.

    Idempotent: only inserts when no DB row exists for the target type.
    Returns the list of credential types that were freshly migrated this
    call (empty when nothing needed migration).

    Args:
        conn: Open SQLite connection.
        encryption: Encryption service initialized with the master key.
        env: Optional override for the env source (tests inject a dict).
            Default reads `shared.config.settings`.
    """
    if env is None:
        from shared.config import settings as _settings

        env = {
            name: getattr(_settings, name, None)
            for name, _ct, _key in _ENV_MIGRATIONS
        }

    migrated: list[CredentialType] = []
    for env_name, cred_type, secret_key in _ENV_MIGRATIONS:
        value = env.get(env_name)
        if not value:
            continue
        existing = conn.execute(
            "SELECT 1 FROM credentials WHERE credential_type = ?",
            (cred_type,),
        ).fetchone()
        if existing is not None:
            # DB row already present — env value is ignored from now on.
            continue
        upsert_credential(
            conn,
            encryption,
            cred_type,
            secrets={secret_key: value},
            notes=f"Auto-migrated from {env_name} on first startup",
            user_id=None,
        )
        emit(
            "credentials",
            "info",
            "env_credential_migrated",
            {"credential_type": cred_type, "env_var": env_name},
        )
        migrated.append(cred_type)
    return migrated
