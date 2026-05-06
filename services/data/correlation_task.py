"""Nightly correlation matrix computation task."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from shared.analytics.correlation import (
    compute_correlation_matrix,
    write_correlation_matrix,
)
from shared.clients.market_data import MarketDataClient
from shared.clients.mock_market_data import DEFAULT_BASELINES
from shared.events import emit

SERVICE_NAME = "data"


def _load_universe(conn: sqlite3.Connection) -> list[str]:
    """Pull universe from active strategy_configs; fall back to mock baselines."""
    row = conn.execute(
        "SELECT settings_json FROM strategy_configs "
        "WHERE name = 'default' AND is_active = 1 LIMIT 1"
    ).fetchone()
    if row and row[0]:
        try:
            settings = json.loads(row[0])
            universe = settings.get("universe")
            if isinstance(universe, list) and universe:
                return [str(t).upper() for t in universe]
        except json.JSONDecodeError:
            pass
    return list(DEFAULT_BASELINES.keys())


async def run_correlation_task(
    client: MarketDataClient,
    conn: sqlite3.Connection,
    lookback_days: int = 30,
) -> int:
    """Compute and persist the correlation matrix. Returns rows written."""
    universe = _load_universe(conn)
    matrix = await compute_correlation_matrix(
        universe, client, lookback_days=lookback_days
    )
    if not matrix.tickers:
        emit(
            SERVICE_NAME,
            "warn",
            "correlation_task_no_data",
            {"requested": len(universe)},
        )
        return 0

    written = write_correlation_matrix(matrix, conn)
    emit(
        SERVICE_NAME,
        "info",
        "correlation_matrix_computed",
        {
            "tickers": matrix.tickers,
            "lookback_days": lookback_days,
            "rows_written": written,
            "date": datetime.now(UTC).date().isoformat(),
        },
    )
    return written
