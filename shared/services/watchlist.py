"""Daily watchlist management with carry-forward fallback."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.events import emit
from shared.services.universe import TickerNotInUniverseError, get_universe
from shared.util.dates import today_et

SERVICE_NAME = "data"


class WatchlistEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str
    tickers: list[str] = Field(default_factory=list)
    per_ticker_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    notes: str | None = None
    created_ts: float
    created_by: Literal["manual", "auto_carry_forward", "system"]


def _row_to_entry(row: tuple[Any, ...]) -> WatchlistEntry:
    # row: (id, date, tickers_json, per_ticker_overrides_json, notes, created_ts, created_by)
    return WatchlistEntry(
        date=row[1],
        tickers=json.loads(row[2] or "[]"),
        per_ticker_overrides=json.loads(row[3] or "{}"),
        notes=row[4],
        created_ts=row[5],
        created_by=row[6],
    )


def _upsert_entry(conn: sqlite3.Connection, entry: WatchlistEntry) -> None:
    conn.execute(
        "INSERT INTO watchlists "
        "(date, tickers_json, per_ticker_overrides_json, notes, created_ts, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(date) DO UPDATE SET "
        "tickers_json = excluded.tickers_json, "
        "per_ticker_overrides_json = excluded.per_ticker_overrides_json, "
        "notes = excluded.notes, "
        "created_ts = excluded.created_ts, "
        "created_by = excluded.created_by",
        (
            entry.date,
            json.dumps(entry.tickers),
            json.dumps(entry.per_ticker_overrides),
            entry.notes,
            entry.created_ts,
            entry.created_by,
        ),
    )
    conn.commit()


def _validate_tickers_against_universe(
    tickers: list[str],
    universe: list[str],
) -> list[str]:
    upper = [t.upper() for t in tickers]
    invalid = [t for t in upper if t not in universe]
    if invalid:
        raise TickerNotInUniverseError(
            f"Tickers not in universe: {invalid}. "
            f"Add them via `universe add` first."
        )
    # Dedup preserving order
    seen: set[str] = set()
    out: list[str] = []
    for t in upper:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


async def get_active_watchlist(conn: sqlite3.Connection) -> WatchlistEntry:
    """Today's watchlist. Carries forward from most recent prior if absent.

    Edge case: no prior watchlist anywhere → returns an empty entry marked
    'system' and emits watchlist_empty.
    """
    today = today_et()
    row = conn.execute(
        "SELECT id, date, tickers_json, per_ticker_overrides_json, notes, "
        "created_ts, created_by FROM watchlists WHERE date = ?",
        (today,),
    ).fetchone()
    if row is not None:
        return _row_to_entry(row)

    prior = conn.execute(
        "SELECT id, date, tickers_json, per_ticker_overrides_json, notes, "
        "created_ts, created_by FROM watchlists ORDER BY date DESC LIMIT 1"
    ).fetchone()
    now_ts = datetime.now().timestamp()
    if prior is None:
        empty = WatchlistEntry(
            date=today,
            tickers=[],
            per_ticker_overrides={},
            notes=None,
            created_ts=now_ts,
            created_by="system",
        )
        emit(SERVICE_NAME, "warn", "watchlist_empty", {"date": today})
        return empty

    prior_entry = _row_to_entry(prior)
    carried = WatchlistEntry(
        date=today,
        tickers=prior_entry.tickers,  # carry tickers
        per_ticker_overrides={},  # do NOT carry overrides — overrides are tactical per-day
        notes=None,
        created_ts=now_ts,
        created_by="auto_carry_forward",
    )
    _upsert_entry(conn, carried)
    emit(
        SERVICE_NAME,
        "info",
        "watchlist_carried_forward",
        {"date": today, "from": prior_entry.date, "ticker_count": len(carried.tickers)},
    )
    return carried


async def set_watchlist(
    conn: sqlite3.Connection,
    tickers: list[str],
    per_ticker_overrides: dict[str, dict[str, Any]] | None = None,
    notes: str | None = None,
    date: str | None = None,
) -> WatchlistEntry:
    target_date = date or today_et()
    universe = await get_universe(conn)
    validated_tickers = _validate_tickers_against_universe(tickers, universe)

    # Validate override keys are also in universe
    overrides = per_ticker_overrides or {}
    invalid_override_keys = [k for k in overrides if k.upper() not in universe]
    if invalid_override_keys:
        raise TickerNotInUniverseError(
            f"Override tickers not in universe: {invalid_override_keys}"
        )
    overrides_upper = {k.upper(): v for k, v in overrides.items()}

    entry = WatchlistEntry(
        date=target_date,
        tickers=validated_tickers,
        per_ticker_overrides=overrides_upper,
        notes=notes,
        created_ts=datetime.now().timestamp(),
        created_by="manual",
    )
    _upsert_entry(conn, entry)
    emit(
        SERVICE_NAME,
        "info",
        "watchlist_set",
        {"date": target_date, "ticker_count": len(validated_tickers)},
    )
    return entry


async def add_ticker_to_watchlist(
    conn: sqlite3.Connection,
    ticker: str,
    overrides: dict[str, Any] | None = None,
    date: str | None = None,
) -> WatchlistEntry:
    upper = ticker.upper()
    universe = await get_universe(conn)
    if upper not in universe:
        raise TickerNotInUniverseError(
            f"{upper} not in universe. Add via `universe add {upper}` first."
        )
    target_date = date or today_et()

    row = conn.execute(
        "SELECT id, date, tickers_json, per_ticker_overrides_json, notes, "
        "created_ts, created_by FROM watchlists WHERE date = ?",
        (target_date,),
    ).fetchone()
    if row is None:
        existing = WatchlistEntry(
            date=target_date,
            tickers=[],
            per_ticker_overrides={},
            notes=None,
            created_ts=datetime.now().timestamp(),
            created_by="manual",
        )
    else:
        existing = _row_to_entry(row)

    new_tickers = list(existing.tickers)
    if upper not in new_tickers:
        new_tickers.append(upper)
    new_overrides = dict(existing.per_ticker_overrides)
    if overrides:
        existing_for_ticker = dict(new_overrides.get(upper, {}))
        existing_for_ticker.update(overrides)
        new_overrides[upper] = existing_for_ticker

    entry = existing.model_copy(
        update={
            "tickers": new_tickers,
            "per_ticker_overrides": new_overrides,
            # If we created a new row above, created_by stays "manual";
            # if we're appending to an existing row, keep its created_by.
        }
    )
    _upsert_entry(conn, entry)
    emit(
        SERVICE_NAME,
        "info",
        "watchlist_ticker_added",
        {"date": target_date, "ticker": upper},
    )
    return entry


async def remove_ticker_from_watchlist(
    conn: sqlite3.Connection,
    ticker: str,
    date: str | None = None,
) -> WatchlistEntry:
    upper = ticker.upper()
    target_date = date or today_et()
    row = conn.execute(
        "SELECT id, date, tickers_json, per_ticker_overrides_json, notes, "
        "created_ts, created_by FROM watchlists WHERE date = ?",
        (target_date,),
    ).fetchone()
    if row is None:
        # Nothing to remove from
        return WatchlistEntry(
            date=target_date,
            tickers=[],
            per_ticker_overrides={},
            notes=None,
            created_ts=datetime.now().timestamp(),
            created_by="manual",
        )
    existing = _row_to_entry(row)
    new_tickers = [t for t in existing.tickers if t != upper]
    new_overrides = {k: v for k, v in existing.per_ticker_overrides.items() if k != upper}
    entry = existing.model_copy(
        update={"tickers": new_tickers, "per_ticker_overrides": new_overrides}
    )
    _upsert_entry(conn, entry)
    emit(
        SERVICE_NAME,
        "info",
        "watchlist_ticker_removed",
        {"date": target_date, "ticker": upper},
    )
    return entry


async def get_watchlist_history(
    conn: sqlite3.Connection,
    days: int = 30,
) -> list[WatchlistEntry]:
    rows = conn.execute(
        "SELECT id, date, tickers_json, per_ticker_overrides_json, notes, "
        "created_ts, created_by FROM watchlists "
        "ORDER BY date DESC LIMIT ?",
        (days,),
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


async def get_per_ticker_overrides(
    conn: sqlite3.Connection,
    ticker: str,
    date: str | None = None,
) -> dict[str, Any]:
    upper = ticker.upper()
    target_date = date or today_et()
    row = conn.execute(
        "SELECT per_ticker_overrides_json FROM watchlists WHERE date = ?",
        (target_date,),
    ).fetchone()
    if row is None or not row[0]:
        return {}
    overrides: dict[str, dict[str, Any]] = json.loads(row[0])
    result: dict[str, Any] = overrides.get(upper, {})
    return result


async def validate_watchlist_universe_sync(
    conn: sqlite3.Connection,
) -> list[str]:
    """Returns tickers in recent watchlists not in the universe. Empty == healthy."""
    universe = set(await get_universe(conn))
    rows = conn.execute(
        "SELECT date, tickers_json FROM watchlists "
        "WHERE date >= date('now', '-7 days')"
    ).fetchall()
    drift: set[str] = set()
    for _date, tickers_json in rows:
        for t in json.loads(tickers_json or "[]"):
            if t.upper() not in universe:
                drift.add(t.upper())
    return sorted(drift)
