"""Background Schwab token refresh task.

Phase 8a.5. Runs every 25 min via apscheduler's IntervalTrigger. Schwab
access tokens expire every 30 min; the 5-min buffer absorbs scheduler
jitter. Refresh tokens have a 7-day rolling window — when fewer than 24
hours remain, this task emits a warning event that the UI uses to surface
a "re-authenticate" banner.

Designed to be safe to invoke when no Schwab credentials are configured;
the data service runs in mixed-mode (mock + Schwab) during onboarding.
"""

from __future__ import annotations

from datetime import UTC, datetime

from shared.db import get_connection
from shared.events import emit
from shared.services.credentials import get_credential_record
from shared.services.encryption import maybe_get_encryption
from shared.services.schwab_refresh import refresh_schwab_token

SERVICE_NAME = "data"
REFRESH_WINDOW_WARN_HOURS = 24.0


async def schwab_refresh_tick() -> None:
    """One iteration of the auto-refresh loop.

    Exceptions are caught and emitted so the apscheduler loop keeps running
    on transient errors.
    """
    try:
        encryption = maybe_get_encryption()
        if encryption is None:
            emit(
                SERVICE_NAME,
                "warn",
                "schwab_refresh_skipped_no_encryption",
                {"reason": "ENCRYPTION_KEY not configured"},
            )
            return

        conn = get_connection()
        try:
            record = get_credential_record(conn, "schwab_oauth")
            if record is None:
                # No Schwab tokens yet — silent no-op so onboarding doesn't
                # spam events before the user has connected.
                return

            if record.refresh_token_expires_at is not None:
                hours_remaining = (
                    record.refresh_token_expires_at - datetime.now(UTC)
                ).total_seconds() / 3600
                if hours_remaining < REFRESH_WINDOW_WARN_HOURS:
                    emit(
                        SERVICE_NAME,
                        "warn",
                        "refresh_token_expiring",
                        {"hours_remaining": round(hours_remaining, 1)},
                    )

            result = await refresh_schwab_token(conn, encryption)
            if not result.success:
                emit(
                    SERVICE_NAME,
                    "error",
                    "auto_refresh_failed",
                    {"message": result.message},
                )
        finally:
            conn.close()
    except Exception as exc:
        emit(
            SERVICE_NAME,
            "error",
            "auto_refresh_exception",
            {"error": str(exc)[:300], "error_type": type(exc).__name__},
        )
