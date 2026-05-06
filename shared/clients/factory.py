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


def make_market_data_client(config: Settings) -> MarketDataClient:
    """Construct the market-data client selected by Settings.DATA_CLIENT.

    Schwab credentials remain in env for Phase 8a — the OAuth flow that
    populates the `schwab_oauth` credential lands in 8c.
    """
    match config.DATA_CLIENT:
        case "mock":
            return MockDataClient(seed=config.MOCK_SEED)
        case "schwab":
            if not config.SCHWAB_CLIENT_ID or not config.SCHWAB_CLIENT_SECRET:
                raise ValueError(
                    "DATA_CLIENT=schwab but SCHWAB_CLIENT_ID/SECRET are empty. "
                    "Add credentials to .env or set DATA_CLIENT=mock."
                )
            return SchwabDataClient(
                client_id=config.SCHWAB_CLIENT_ID,
                client_secret=config.SCHWAB_CLIENT_SECRET,
                redirect_uri=config.SCHWAB_REDIRECT_URI,
                token_path=config.SCHWAB_TOKEN_PATH,
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
