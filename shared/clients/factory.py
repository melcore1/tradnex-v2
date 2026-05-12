"""Client factories.

Phase 8a: provider keys (Finnhub, Exa) are read from the encrypted
`credentials` table when available, and fall back to env (`Settings.*`) only
when the DB row doesn't exist. This safety-net keeps tests that monkeypatch
env vars working until they're updated.

Pass an open SQLite connection + an EncryptionService to enable the DB
lookup. Callers without a connection (legacy code paths, the orchestrator
CLI) fall back to env-only behavior — that path will be removed in 8b.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from shared.clients.calendar_feed import CalendarFeed
from shared.clients.claude_cli import ClaudeCliClient
from shared.clients.exa_news import ExaClient, ExaNewsClient
from shared.clients.finnhub_calendar import FinnhubCalendarClient
from shared.clients.halt_feed import HaltFeed
from shared.clients.market_data import MarketDataClient
from shared.clients.mock_calendar import MockCalendarClient
from shared.clients.mock_claude_cli import MockClaudeCliClient
from shared.clients.mock_exa_news import MockExaClient
from shared.clients.mock_halt_feed import MockHaltFeed
from shared.clients.mock_market_data import MockDataClient
from shared.clients.nasdaq_halt_feed import NasdaqHaltFeed
from shared.clients.schwab_market_data import SchwabDataClient
from shared.config import Settings
from shared.services.credentials import (
    CredentialType,
    get_credential_secrets,
)
from shared.services.encryption import (
    EncryptionService,
    InvalidEncryptionKeyError,
)


def _resolve_secret(
    *,
    credential_type: CredentialType,
    secret_key: str,
    env_value: str | None,
    conn: sqlite3.Connection | None,
    encryption: EncryptionService | None,
) -> str | None:
    """Look up a secret by preferring the credentials store, falling back to env.

    Returns None when neither source has it. Decryption failures degrade to
    the env value (and emit nothing themselves — credentials.py emits when
    decryption fails downstream).
    """
    if conn is not None and encryption is not None:
        try:
            secrets = get_credential_secrets(conn, encryption, credential_type)
        except InvalidEncryptionKeyError:
            secrets = None
        if secrets and secret_key in secrets:
            return str(secrets[secret_key])
    return env_value


class DataClientNotConfigured(RuntimeError):
    """DATA_CLIENT=schwab but the encrypted credentials store isn't ready."""


def make_market_data_client(
    config: Settings,
    *,
    db: sqlite3.Connection | None = None,
    encryption: EncryptionService | None = None,
) -> MarketDataClient:
    """Construct the market-data client selected by Settings.DATA_CLIENT.

    Phase 8a.5: when DATA_CLIENT=schwab, the factory reads `schwab_client`
    (Client ID/Secret) from the encrypted credentials store and builds a
    `tokens_provider` closure that returns the latest `schwab_oauth`
    tokens on every Schwab API call. `db` and `encryption` are
    auto-resolved from `shared.db.get_connection()` and
    `shared.services.encryption.maybe_get_encryption()` when not passed,
    so all existing single-arg callers (scanner, monitor, orchestrator,
    evaluator, CLIs) keep working.

    Raises:
        DataClientNotConfigured: when DATA_CLIENT=schwab but ENCRYPTION_KEY
            isn't configured, or when the `schwab_client` credential isn't
            seeded yet.
    """
    match config.DATA_CLIENT:
        case "mock":
            return MockDataClient(seed=config.MOCK_SEED)
        case "schwab":
            from shared.db import get_connection
            from shared.services.encryption import maybe_get_encryption

            owns_db = db is None
            if encryption is None:
                encryption = maybe_get_encryption()
            if encryption is None:
                raise DataClientNotConfigured(
                    "DATA_CLIENT=schwab requires ENCRYPTION_KEY to be "
                    "configured so the credentials store is readable."
                )

            local_db = db if db is not None else get_connection()
            try:
                client_secrets = get_credential_secrets(
                    local_db, encryption, "schwab_client"
                )
            finally:
                if owns_db:
                    local_db.close()

            if (
                not client_secrets
                or not client_secrets.get("client_id")
                or not client_secrets.get("client_secret")
            ):
                raise DataClientNotConfigured(
                    "DATA_CLIENT=schwab but schwab_client credential not "
                    "configured. Visit Settings → Credentials → Schwab to "
                    "enter Client ID and Secret."
                )

            # Bind a non-None reference so the closure passes mypy strict.
            encryption_ref = encryption

            def _tokens_provider() -> dict[str, Any]:
                # Open a fresh connection each call so we always see the
                # latest tokens written by the 25-min refresh task.
                from datetime import UTC
                from datetime import datetime as _dt

                from shared.services.credentials import get_credential_record

                conn = get_connection()
                try:
                    tokens = get_credential_secrets(
                        conn, encryption_ref, "schwab_oauth", use_cache=False
                    )
                    record = get_credential_record(conn, "schwab_oauth")
                finally:
                    conn.close()
                if not tokens:
                    raise DataClientNotConfigured(
                        "schwab_oauth tokens missing — connect via "
                        "Settings → Credentials → Schwab."
                    )
                # schwab-py wraps authlib's OAuth2Token, which needs either
                # `expires_at` (epoch) or `expires_in` (seconds). We persist
                # the access-token expiry in the DB `expires_at` column,
                # not inside the secrets dict, so inject it here.
                merged = dict(tokens)
                if record is not None and record.expires_at is not None:
                    expires_epoch = int(record.expires_at.timestamp())
                    merged.setdefault("expires_at", expires_epoch)
                    now_epoch = int(_dt.now(UTC).timestamp())
                    merged.setdefault(
                        "expires_in", max(0, expires_epoch - now_epoch)
                    )
                return merged

            return SchwabDataClient(
                client_id=str(client_secrets["client_id"]),
                client_secret=str(client_secrets["client_secret"]),
                tokens_provider=_tokens_provider,
            )
        case _:
            raise ValueError(f"Unknown DATA_CLIENT: {config.DATA_CLIENT}")


def make_halt_feed(config: Settings) -> HaltFeed:
    """Construct the halt feed selected by Settings.HALT_FEED."""
    match config.HALT_FEED:
        case "mock":
            return MockHaltFeed()
        case "nasdaq":
            return NasdaqHaltFeed(
                poll_interval_seconds=config.HALT_POLL_MARKET_SECONDS,
            )
        case _:
            raise ValueError(f"Unknown HALT_FEED: {config.HALT_FEED}")


def make_calendar_client(
    config: Settings,
    *,
    conn: sqlite3.Connection | None = None,
    encryption: EncryptionService | None = None,
) -> CalendarFeed:
    """Pick mock vs Finnhub based on credential availability.

    Lookup order: credentials store → env (Phase 8a fallback) → mock.
    The mock auto-seeds plausible upcoming events; the Finnhub client hits
    the live API and degrades to empty lists on errors.
    """
    api_key = _resolve_secret(
        credential_type="finnhub",
        secret_key="api_key",
        env_value=config.FINNHUB_API_KEY,
        conn=conn,
        encryption=encryption,
    )
    if api_key:
        return FinnhubCalendarClient(api_key)
    return MockCalendarClient()


def make_exa_client(
    config: Settings,
    *,
    conn: sqlite3.Connection | None = None,
    encryption: EncryptionService | None = None,
) -> ExaClient:
    """Pick mock vs real Exa based on credential availability.

    Lookup order: credentials store → env (Phase 8a fallback) → mock.
    """
    api_key = _resolve_secret(
        credential_type="exa",
        secret_key="api_key",
        env_value=config.EXA_API_KEY,
        conn=conn,
        encryption=encryption,
    )
    if api_key:
        return ExaNewsClient(api_key)
    return MockExaClient()


def make_claude_client(
    config: Settings,
) -> ClaudeCliClient | MockClaudeCliClient:
    """Pick the Claude client based on Settings.CLAUDE_CLIENT.

    'mock' → MockClaudeCliClient (use inject_response in tests/dev).
    'cli'  → ClaudeCliClient invoking the local `claude -p` subprocess.

    The CLI subprocess uses ambient `~/.claude/` session, so no API key
    is read here. Phase 8a keeps the CLI path; a future phase may add a
    direct-API alternative that consults the credentials store.
    """
    match config.CLAUDE_CLIENT:
        case "mock":
            return MockClaudeCliClient(model=config.CLAUDE_MODEL)
        case "cli":
            return ClaudeCliClient(
                model=config.CLAUDE_MODEL,
                timeout_seconds=config.CLAUDE_TIMEOUT_SECONDS,
                cli_path=config.CLAUDE_CLI_PATH,
            )
        case _:
            raise ValueError(f"Unknown CLAUDE_CLIENT: {config.CLAUDE_CLIENT}")
