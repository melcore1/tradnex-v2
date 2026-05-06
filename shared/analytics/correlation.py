"""Pairwise Pearson correlation across a static universe.

Computed nightly into ``correlation_snapshots``; scanner reads from cache.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from shared.clients.market_data import MarketDataClient


class CorrelationMatrix(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    lookback_days: int
    tickers: list[str]
    matrix: dict[str, dict[str, Decimal]] = Field(default_factory=dict)

    def get(self, ticker_a: str, ticker_b: str) -> Decimal | None:
        a, b = ticker_a.upper(), ticker_b.upper()
        if a in self.matrix and b in self.matrix[a]:
            return self.matrix[a][b]
        return None

    def highly_correlated_with(
        self,
        ticker: str,
        threshold: Decimal = Decimal("0.85"),
    ) -> list[tuple[str, Decimal]]:
        a = ticker.upper()
        row = self.matrix.get(a, {})
        out = [
            (other, value)
            for other, value in row.items()
            if other != a and abs(value) >= threshold
        ]
        return sorted(out, key=lambda kv: abs(kv[1]), reverse=True)


async def compute_correlation_matrix(
    tickers: list[str],
    client: MarketDataClient,
    lookback_days: int = 30,
) -> CorrelationMatrix:
    """Pearson correlation of log returns over the lookback window.

    Per-ticker insufficient bars → that ticker is dropped from the result
    rather than failing the whole computation.
    """
    needed = lookback_days + 1
    returns_by_ticker: dict[str, np.ndarray] = {}
    for t in tickers:
        bars = await client.get_bars(t, timeframe="1d", limit=needed)
        if len(bars) < needed:
            continue
        closes = np.array([float(b.close) for b in bars], dtype=np.float64)
        if (closes <= 0).any():
            continue
        log_returns = np.diff(np.log(closes))
        returns_by_ticker[t.upper()] = log_returns

    valid_tickers = list(returns_by_ticker.keys())
    matrix: dict[str, dict[str, Decimal]] = {}
    if not valid_tickers:
        return CorrelationMatrix(
            timestamp=datetime.now(UTC),
            lookback_days=lookback_days,
            tickers=[],
            matrix={},
        )

    stacked = np.stack([returns_by_ticker[t] for t in valid_tickers])
    corr = np.corrcoef(stacked)
    # corrcoef returns a 0-d scalar when stacked has only 1 row
    corr_2d = np.atleast_2d(corr)
    for i, a in enumerate(valid_tickers):
        matrix[a] = {}
        for j, b in enumerate(valid_tickers):
            value = corr_2d[i][j] if corr_2d.ndim == 2 else (1.0 if i == j else 0.0)
            if np.isnan(value):
                matrix[a][b] = Decimal("0")
            else:
                matrix[a][b] = Decimal(str(round(float(value), 6)))

    return CorrelationMatrix(
        timestamp=datetime.now(UTC),
        lookback_days=lookback_days,
        tickers=valid_tickers,
        matrix=matrix,
    )


def _most_recent_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT date FROM correlation_snapshots ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def get_correlation_matrix(
    tickers: list[str],
    conn: sqlite3.Connection,
    date: str | None = None,
    lookback_days: int = 30,
) -> CorrelationMatrix:
    """Read cached correlation matrix from ``correlation_snapshots``."""
    if date is None:
        date = _most_recent_date(conn)
    if date is None:
        return CorrelationMatrix(
            timestamp=datetime.now(UTC),
            lookback_days=lookback_days,
            tickers=[],
            matrix={},
        )

    upper_tickers = [t.upper() for t in tickers]
    placeholders = ",".join("?" * len(upper_tickers))
    rows = conn.execute(
        f"SELECT ticker_a, ticker_b, correlation, lookback_days "
        f"FROM correlation_snapshots WHERE date = ? "
        f"AND ticker_a IN ({placeholders}) AND ticker_b IN ({placeholders})",
        (date, *upper_tickers, *upper_tickers),
    ).fetchall()

    matrix: dict[str, dict[str, Decimal]] = {t: {} for t in upper_tickers}
    seen_lookback = lookback_days
    for a, b, corr, lb in rows:
        seen_lookback = lb
        matrix.setdefault(a, {})[b] = Decimal(str(corr))
    # Diagonal
    for t in upper_tickers:
        matrix.setdefault(t, {}).setdefault(t, Decimal("1.0"))

    present_tickers = [t for t in upper_tickers if matrix.get(t)]
    return CorrelationMatrix(
        timestamp=datetime.now(UTC),
        lookback_days=seen_lookback,
        tickers=present_tickers,
        matrix=matrix,
    )


def write_correlation_matrix(
    matrix: CorrelationMatrix,
    conn: sqlite3.Connection,
    *,
    date: str | None = None,
) -> int:
    """Persist a CorrelationMatrix into ``correlation_snapshots`` (UPSERT)."""
    write_date = date or matrix.timestamp.date().isoformat()
    rows: list[tuple[str, str, str, float, int, float]] = []
    seen: set[tuple[str, str]] = set()
    for a, row in matrix.matrix.items():
        for b, value in row.items():
            key = (a, b)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                (
                    write_date,
                    a,
                    b,
                    float(value),
                    matrix.lookback_days,
                    datetime.now(UTC).timestamp(),
                )
            )
    conn.executemany(
        "INSERT OR REPLACE INTO correlation_snapshots "
        "(date, ticker_a, ticker_b, correlation, lookback_days, computed_ts) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)
