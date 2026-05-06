"""Integration test: compute_options_analysis end-to-end via mock client."""


import pytest

from shared.analytics import (
    FullOptionsAnalysis,
    compute_full_analysis,
    compute_options_analysis,
)
from shared.clients.mock_market_data import MockDataClient


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "options_full.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    return db_mod


async def test_compute_options_analysis_populates_every_field(fresh_db) -> None:
    client = MockDataClient(seed=42)
    client.seed_iv_history()

    chain = await client.get_options_chain("NVDA")
    bars = await client.get_bars("NVDA", timeframe="1d", limit=300)
    fa = await compute_full_analysis("NVDA", bars, timeframe="1d")

    conn = fresh_db.get_connection()
    try:
        oa = compute_options_analysis(chain, conn, garch_result=fa.garch)
    finally:
        conn.close()

    assert isinstance(oa, FullOptionsAnalysis)
    assert oa.ticker == "NVDA"
    assert oa.gex.net_gex is not None
    assert len(oa.gex_by_expiration) > 0
    assert oa.iv_rank.rank is not None or oa.iv_rank.data_points > 0
    assert oa.skew is not None
    assert oa.term_structure is not None
    assert oa.vrp is not None  # GARCH provided
    assert oa.pc_ratio.oi_pc_ratio is not None
    assert len(oa.max_pain_per_expiration) > 0
    assert len(oa.expected_move_per_expiration) > 0
    # 0DTE may or may not be present depending on whether today is an expiry; either is valid


async def test_summary_mentions_ticker(fresh_db) -> None:
    client = MockDataClient(seed=42)
    client.seed_iv_history()
    chain = await client.get_options_chain("AAPL")
    bars = await client.get_bars("AAPL", timeframe="1d", limit=300)
    fa = await compute_full_analysis("AAPL", bars, timeframe="1d")
    conn = fresh_db.get_connection()
    try:
        oa = compute_options_analysis(chain, conn, garch_result=fa.garch)
    finally:
        conn.close()
    assert "AAPL" in oa.summary
    assert "GEX" in oa.summary or "gex" in oa.summary.lower()


async def test_serializes_to_json(fresh_db) -> None:
    client = MockDataClient(seed=42)
    client.seed_iv_history()
    chain = await client.get_options_chain("SPY")
    bars = await client.get_bars("SPY", timeframe="1d", limit=300)
    fa = await compute_full_analysis("SPY", bars, timeframe="1d")
    conn = fresh_db.get_connection()
    try:
        oa = compute_options_analysis(chain, conn, garch_result=fa.garch)
    finally:
        conn.close()
    blob = oa.model_dump_json()
    assert "SPY" in blob
    assert "iv_rank" in blob
    assert "gex" in blob


async def test_no_garch_means_no_vrp(fresh_db) -> None:
    client = MockDataClient(seed=42)
    client.seed_iv_history()
    chain = await client.get_options_chain("NVDA")
    conn = fresh_db.get_connection()
    try:
        oa = compute_options_analysis(chain, conn, garch_result=None)
    finally:
        conn.close()
    assert oa.vrp is None
