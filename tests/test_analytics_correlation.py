"""Correlation matrix computation + storage tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from shared.analytics import (
    CorrelationMatrix,
    compute_correlation_matrix,
    get_correlation_matrix,
    write_correlation_matrix,
)
from shared.clients.market_data import MarketDataClient
from shared.schemas.market import Bar


class _DeterministicClient(MarketDataClient):
    """Returns precomputed bars for tickers, lets tests dial correlation precisely."""

    def __init__(self, closes_by_ticker: dict[str, list[float]]) -> None:
        self._closes = closes_by_ticker

    async def get_quote(self, ticker):  # pragma: no cover
        raise NotImplementedError

    async def get_quotes(self, tickers):  # pragma: no cover
        raise NotImplementedError

    async def get_bars(self, ticker, timeframe="1d", limit=200, end=None):
        closes = self._closes.get(ticker.upper(), [])[:limit]
        bars: list[Bar] = []
        for i, c in enumerate(closes):
            bars.append(
                Bar(
                    timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i),
                    open=Decimal(str(c)),
                    high=Decimal(str(c + 0.5)),
                    low=Decimal(str(c - 0.5)),
                    close=Decimal(str(c)),
                    volume=1_000_000,
                )
            )
        return bars

    async def get_options_chain(  # pragma: no cover
        self,
        ticker,
        min_dte=None,
        max_dte=None,
        contract_type="both",
    ):
        raise NotImplementedError

    async def get_account_state(self):  # pragma: no cover
        raise NotImplementedError

    async def get_movers(self):  # pragma: no cover
        raise NotImplementedError

    async def get_market_status(self):  # pragma: no cover
        raise NotImplementedError

    async def health_check(self):
        return True


@pytest.fixture
def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "corr.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


async def test_perfect_correlation() -> None:
    rng = np.random.default_rng(7)
    base = list(100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 50))))
    client = _DeterministicClient({"A": base, "B": [x * 1.05 for x in base]})
    matrix = await compute_correlation_matrix(["A", "B"], client, lookback_days=30)
    val = matrix.get("A", "B")
    assert val is not None
    assert float(val) > 0.99


async def test_anti_correlation() -> None:
    rng = np.random.default_rng(7)
    base = list(100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 50))))
    inverse = [200 - x for x in base]
    client = _DeterministicClient({"A": base, "B": inverse})
    matrix = await compute_correlation_matrix(["A", "B"], client, lookback_days=30)
    val = matrix.get("A", "B")
    assert val is not None
    assert float(val) < -0.5


async def test_matrix_symmetric_and_diagonal() -> None:
    rng = np.random.default_rng(1)
    a = list(100 + np.cumsum(rng.normal(0.0, 1.0, 40)))
    b = list(100 + np.cumsum(rng.normal(0.0, 1.0, 40)))
    client = _DeterministicClient({"A": a, "B": b})
    matrix = await compute_correlation_matrix(["A", "B"], client, lookback_days=30)
    assert matrix.get("A", "B") == matrix.get("B", "A")
    diagonal = matrix.get("A", "A")
    assert diagonal is not None and float(diagonal) == pytest.approx(1.0)


async def test_highly_correlated_with_filter() -> None:
    rng = np.random.default_rng(7)
    base = list(100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 50))))
    client = _DeterministicClient(
        {"A": base, "B": [x * 1.05 for x in base], "C": list(100 + rng.normal(0, 5, 50))}
    )
    matrix = await compute_correlation_matrix(["A", "B", "C"], client, lookback_days=30)
    matches = matrix.highly_correlated_with("A", threshold=Decimal("0.8"))
    tickers = {m[0] for m in matches}
    assert "B" in tickers


async def test_storage_roundtrip(db_conn) -> None:
    matrix = CorrelationMatrix(
        timestamp=datetime.now(UTC),
        lookback_days=30,
        tickers=["A", "B"],
        matrix={
            "A": {"A": Decimal("1.0"), "B": Decimal("0.75")},
            "B": {"A": Decimal("0.75"), "B": Decimal("1.0")},
        },
    )
    written = write_correlation_matrix(matrix, db_conn)
    assert written == 4
    cached = get_correlation_matrix(["A", "B"], db_conn)
    assert cached.get("A", "B") == Decimal("0.75")


async def test_insufficient_bars_excludes_ticker() -> None:
    client = _DeterministicClient({"A": [100, 101, 102], "B": [100, 101, 102, 103, 104] * 10})
    matrix = await compute_correlation_matrix(["A", "B"], client, lookback_days=30)
    assert "A" not in matrix.tickers
