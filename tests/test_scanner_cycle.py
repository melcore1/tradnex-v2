"""Scan cycle behavior: persistence, errors, overrides."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from services.scanner.cycle import evaluate_ticker, run_scan_cycle
from shared.analytics.full_analysis import FullAnalysis
from shared.clients.mock_market_data import MockDataClient
from shared.services.watchlist import set_watchlist
from shared.strategy.base import (
    EntryCandidate,
    RuleResult,
    RuleTrace,
    RuleType,
)
from shared.strategy.long_options_momentum import LongOptionsMomentum


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "cycle.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


@pytest.fixture
def client():
    c = MockDataClient(seed=42)
    c.seed_iv_history()
    return c


def _make_trace(*, fired: bool, soft_score: int = 0, ticker: str = "NVDA") -> RuleTrace:
    h = RuleResult(name="H", rule_type=RuleType.HARD, passed=fired, score=1, max_score=1)
    s = RuleResult(name="S", rule_type=RuleType.SOFT, passed=fired, score=soft_score, max_score=2)
    return RuleTrace(
        timestamp=datetime.now(UTC),
        ticker=ticker,
        hard_rules=[h, h, h],
        soft_rules=[s, s, s],
        all_hard_passed=fired,
        soft_score=soft_score,
        soft_max_score=6,
        confidence_label="STRONG" if fired else "VETO",
        confidence_score=Decimal(soft_score) / Decimal("6"),
        fired=fired,
        fire_decision_reason="all_hard_passed_soft_score_5" if fired else "veto",
    )


def _make_candidate(fa: FullAnalysis, ticker: str = "NVDA") -> EntryCandidate:
    assert fa.regime is not None
    return EntryCandidate(
        ticker=ticker,
        direction="long_call",
        strategy_name="long_options_momentum",
        rule_trace=_make_trace(fired=True, soft_score=5, ticker=ticker),
        full_analysis=fa,
        options_analysis=None,
        regime=fa.regime,
        confidence="STRONG",
        sizing_multiplier=Decimal("1.0"),
        max_premium=Decimal("500"),
        timestamp=datetime.now(UTC),
    )


async def test_empty_watchlist_skips_with_event(db_conn, client) -> None:
    strategy = LongOptionsMomentum()
    result = await run_scan_cycle(client, db_conn, strategy)
    assert result.tickers_evaluated == 0
    assert result.candidates_fired == 0
    rows = db_conn.execute(
        "SELECT event_type FROM events WHERE event_type = 'scanner_skipped_empty_watchlist'"
    ).fetchall()
    assert len(rows) >= 1


async def test_full_run_counts_tickers(db_conn, client) -> None:
    await set_watchlist(db_conn, ["NVDA", "AMD"])
    strategy = LongOptionsMomentum()
    result = await run_scan_cycle(client, db_conn, strategy)
    assert result.tickers_evaluated == 2
    assert len(result.errors) == 0
    eval_count = db_conn.execute(
        "SELECT COUNT(*) FROM scanner_evaluations"
    ).fetchone()[0]
    assert eval_count == 2


async def test_one_ticker_raises_others_continue(db_conn, client) -> None:
    await set_watchlist(db_conn, ["NVDA", "AMD", "SPY"])
    strategy = LongOptionsMomentum()
    original_get_bars = client.get_bars

    async def faulty_bars(ticker, timeframe, limit=200, end=None):
        if ticker.upper() == "AMD":
            raise RuntimeError("simulated upstream error")
        return await original_get_bars(ticker, timeframe, limit=limit, end=end)

    with patch.object(client, "get_bars", side_effect=faulty_bars):
        result = await run_scan_cycle(client, db_conn, strategy)
    assert result.tickers_evaluated == 2
    assert len(result.errors) == 1
    assert result.errors[0]["ticker"] == "AMD"
    rows = db_conn.execute(
        "SELECT payload FROM events WHERE event_type = 'scanner_ticker_error'"
    ).fetchall()
    assert any("AMD" in row["payload"] for row in rows)


async def test_candidate_fired_writes_both_tables(db_conn, client) -> None:
    """Force the strategy to fire a candidate; both candidates and scanner_evaluations
    rows must be populated and FK-linked."""

    await set_watchlist(db_conn, ["NVDA"])

    async def stub_evaluate_entry(*args, **kwargs):
        full_analysis = kwargs["full_analysis"]
        trace = _make_trace(fired=True, soft_score=5)
        candidate = _make_candidate(full_analysis)
        return trace, candidate

    def stub_shortlist(chain, direction, params=None):
        # Return at least one contract so the cycle does not downgrade
        return [c for c in chain.contracts if c.contract_type == "call"][:1]

    strategy = LongOptionsMomentum()
    with (
        patch.object(strategy, "evaluate_entry", side_effect=stub_evaluate_entry),
        patch("services.scanner.cycle.build_shortlist", side_effect=stub_shortlist),
    ):
        result = await run_scan_cycle(client, db_conn, strategy)
    assert result.candidates_fired == 1

    cand_count = db_conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    eval_count = db_conn.execute("SELECT COUNT(*) FROM scanner_evaluations").fetchone()[0]
    assert cand_count == 1
    assert eval_count == 1
    fk = db_conn.execute(
        "SELECT candidate_id FROM scanner_evaluations LIMIT 1"
    ).fetchone()[0]
    assert fk == 1


async def test_no_candidate_only_evaluation_row(db_conn, client) -> None:
    await set_watchlist(db_conn, ["NVDA"])
    strategy = LongOptionsMomentum()
    # Without forcing, rules will likely not all pass on mock data — just verify
    # that no candidate row is created when evaluate_entry returns (trace, None).
    with patch.object(
        strategy,
        "evaluate_entry",
        AsyncMock(return_value=(_make_trace(fired=False), None)),
    ):
        await run_scan_cycle(client, db_conn, strategy)
    cand_count = db_conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    eval_count = db_conn.execute("SELECT COUNT(*) FROM scanner_evaluations").fetchone()[0]
    assert cand_count == 0
    assert eval_count == 1


async def test_cycle_id_propagates(db_conn, client) -> None:
    await set_watchlist(db_conn, ["NVDA", "AMD"])
    strategy = LongOptionsMomentum()
    result = await run_scan_cycle(client, db_conn, strategy, cycle_id="custom-id-1")
    assert result.cycle_id == "custom-id-1"
    rows = db_conn.execute(
        "SELECT DISTINCT cycle_id FROM scanner_evaluations"
    ).fetchall()
    assert {row["cycle_id"] for row in rows} == {"custom-id-1"}


async def test_per_ticker_override_passed_to_strategy(db_conn, client) -> None:
    await set_watchlist(
        db_conn,
        ["NVDA"],
        per_ticker_overrides={"NVDA": {"volume_mult_min": 1.5}},
    )
    strategy = LongOptionsMomentum()
    captured: dict[str, Any] = {}

    async def capture_overrides(*args, **kwargs):
        captured["overrides"] = kwargs.get("overrides")
        return _make_trace(fired=False), None

    with patch.object(strategy, "evaluate_entry", side_effect=capture_overrides):
        await run_scan_cycle(client, db_conn, strategy)
    assert captured["overrides"] == {"volume_mult_min": 1.5}


async def test_shortlist_empty_downgrades_to_no_fire(db_conn, client) -> None:
    """When shortlist is empty after build, candidate is downgraded."""
    await set_watchlist(db_conn, ["NVDA"])

    async def stub_eval(*args, **kwargs):
        full_analysis = kwargs["full_analysis"]
        return _make_trace(fired=True, soft_score=5), _make_candidate(full_analysis)

    strategy = LongOptionsMomentum()
    with (
        patch.object(strategy, "evaluate_entry", side_effect=stub_eval),
        patch(
            "services.scanner.cycle.build_shortlist",
            return_value=[],
        ),
    ):
        result = await run_scan_cycle(client, db_conn, strategy)
    assert result.candidates_fired == 0
    cand_count = db_conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    assert cand_count == 0
    eval_row = db_conn.execute(
        "SELECT rule_trace_json FROM scanner_evaluations LIMIT 1"
    ).fetchone()
    trace = RuleTrace.model_validate_json(eval_row["rule_trace_json"])
    assert trace.fired is False
    assert trace.fire_decision_reason == "shortlist_empty_insufficient_dte_diversity"


async def test_evaluate_ticker_returns_trace_and_no_candidate_on_veto(
    db_conn, client
) -> None:
    strategy = LongOptionsMomentum()
    with patch.object(
        strategy,
        "evaluate_entry",
        AsyncMock(return_value=(_make_trace(fired=False), None)),
    ):
        result = await evaluate_ticker(
            ticker="NVDA",
            client=client,
            conn=db_conn,
            strategy=strategy,
            overrides={},
            cycle_id="cyc",
        )
    assert result.candidate is None
    assert result.candidate_id is None
    assert result.rule_trace.fired is False


async def test_evaluate_ticker_returns_candidate_when_fired(db_conn, client) -> None:
    strategy = LongOptionsMomentum()

    async def stub_eval(*args, **kwargs):
        return _make_trace(fired=True, soft_score=5), _make_candidate(
            kwargs["full_analysis"]
        )

    def stub_shortlist(chain, direction, params=None):
        return [c for c in chain.contracts if c.contract_type == "call"][:1]

    with (
        patch.object(strategy, "evaluate_entry", side_effect=stub_eval),
        patch("services.scanner.cycle.build_shortlist", side_effect=stub_shortlist),
    ):
        result = await evaluate_ticker(
            ticker="NVDA",
            client=client,
            conn=db_conn,
            strategy=strategy,
            overrides={},
            cycle_id="cyc",
        )
    assert result.candidate is not None
    assert result.candidate_id is not None
    assert result.rule_trace.fired is True
