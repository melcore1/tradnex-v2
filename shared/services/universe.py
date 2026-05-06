"""Universe management: the set of tickers the system is allowed to trade.

Stored in the active strategy_config's settings_json["universe"] field.
Source of truth for ticker validity — every watchlist entry must be in the
universe.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from shared.events import emit

DEFAULT_UNIVERSE = [
    "NVDA",
    "AMD",
    "SPY",
    "QQQ",
    "SOXL",
    "TSLA",
    "MSFT",
    "AAPL",
    "META",
    "GOOGL",
]

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}$")
SERVICE_NAME = "data"


class InvalidTickerError(ValueError):
    """Raised when a ticker doesn't match the expected format."""


class TickerNotInUniverseError(ValueError):
    """Raised when a watchlist operation references a ticker outside the universe."""


def _validate_ticker(ticker: str) -> str:
    upper = ticker.upper().strip()
    if not _TICKER_RE.match(upper):
        raise InvalidTickerError(
            f"Invalid ticker {ticker!r}: must be 1-6 chars, uppercase letters/digits only"
        )
    return upper


def _load_settings(conn: sqlite3.Connection) -> tuple[int, dict[str, Any]]:
    row = conn.execute(
        "SELECT id, settings_json FROM strategy_configs "
        "WHERE name = 'default' AND is_active = 1 LIMIT 1"
    ).fetchone()
    if not row:
        raise RuntimeError(
            "No active default strategy_config — migrations may not have run"
        )
    settings = json.loads(row[1] or "{}")
    return row[0], settings


def _save_settings(
    conn: sqlite3.Connection,
    config_id: int,
    settings: dict[str, Any],
) -> None:
    conn.execute(
        "UPDATE strategy_configs SET settings_json = ?, updated_ts = strftime('%s','now') "
        "WHERE id = ?",
        (json.dumps(settings), config_id),
    )
    conn.commit()


async def get_universe(conn: sqlite3.Connection) -> list[str]:
    """Returns the configured universe; falls back to defaults when unseeded."""
    _, settings = _load_settings(conn)
    universe = settings.get("universe")
    if not universe:
        return list(DEFAULT_UNIVERSE)
    return [t.upper() for t in universe]


async def is_in_universe(conn: sqlite3.Connection, ticker: str) -> bool:
    universe = await get_universe(conn)
    return ticker.upper() in universe


async def add_to_universe(conn: sqlite3.Connection, ticker: str) -> list[str]:
    """Add a ticker to the universe. Idempotent. Returns the updated universe."""
    upper = _validate_ticker(ticker)
    config_id, settings = _load_settings(conn)
    current = list(settings.get("universe") or DEFAULT_UNIVERSE)
    if upper in current:
        return current
    current.append(upper)
    settings["universe"] = current
    _save_settings(conn, config_id, settings)
    emit(
        SERVICE_NAME,
        "info",
        "universe_changed",
        {"action": "added", "ticker": upper, "universe_size": len(current)},
    )
    return current


async def remove_from_universe(conn: sqlite3.Connection, ticker: str) -> list[str]:
    """Remove a ticker from universe. Cascades to any watchlists holding it."""
    upper = _validate_ticker(ticker)
    config_id, settings = _load_settings(conn)
    current = list(settings.get("universe") or DEFAULT_UNIVERSE)
    if upper not in current:
        return current
    current = [t for t in current if t != upper]
    settings["universe"] = current
    _save_settings(conn, config_id, settings)

    # Cascade: remove ticker from any existing watchlist
    rows = conn.execute(
        "SELECT id, tickers_json, per_ticker_overrides_json FROM watchlists"
    ).fetchall()
    for row_id, tickers_json, overrides_json in rows:
        tickers = json.loads(tickers_json or "[]")
        overrides = json.loads(overrides_json or "{}")
        if upper not in tickers and upper not in overrides:
            continue
        new_tickers = [t for t in tickers if t != upper]
        new_overrides = {k: v for k, v in overrides.items() if k != upper}
        conn.execute(
            "UPDATE watchlists SET tickers_json = ?, per_ticker_overrides_json = ? "
            "WHERE id = ?",
            (json.dumps(new_tickers), json.dumps(new_overrides), row_id),
        )
    conn.commit()

    emit(
        SERVICE_NAME,
        "info",
        "universe_changed",
        {"action": "removed", "ticker": upper, "universe_size": len(current)},
    )
    return current
