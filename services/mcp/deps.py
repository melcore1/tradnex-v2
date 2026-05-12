"""Dependency helpers for MCP tools.

Each tool runs in its own request task; we open a *fresh* sqlite3 connection
per call rather than sharing one (SQLite in WAL mode handles concurrent
readers; FastAPI uses the same per-request pattern). The encryption service
and market-data client are lazily resolved from process state.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING

from shared.clients.factory import make_market_data_client
from shared.db import get_connection
from shared.services.encryption import EncryptionService, maybe_get_encryption

if TYPE_CHECKING:
    from collections.abc import Iterator

    from shared.clients.market_data import MarketDataClient


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    """Open a sqlite3 connection for the duration of one tool call."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_encryption_or_raise() -> EncryptionService:
    """Return the process-wide EncryptionService, or raise if ENCRYPTION_KEY missing."""
    enc = maybe_get_encryption()
    if enc is None:
        raise RuntimeError(
            "MCP server requires ENCRYPTION_KEY env var. "
            "Run `python -m services.api.cli generate-encryption-key` to create one."
        )
    return enc


def build_data_client() -> MarketDataClient:
    """Resolve the current MarketDataClient via the shared factory.

    Reads `DATA_CLIENT` from `shared.config.settings`. When schwab, the
    factory pulls credentials from the encrypted store on each `tokens_provider`
    invocation, so this client tracks DB state automatically.
    """
    from shared.config import settings

    return make_market_data_client(settings)
