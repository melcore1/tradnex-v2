"""Persistence layer for candidates + scanner_evaluations."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from services.scanner.persistence import (
    fetch_candidate,
    fetch_recent_evaluations,
    persist_candidate,
    persist_evaluation,
)
from shared.analytics.full_analysis import compute_full_analysis
from shared.clients.mock_market_data import MockDataClient
from shared.strategy.base import (
    EntryCandidate,
    RuleResult,
    RuleTrace,
    RuleType,
)


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "scanner.db"))
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
async def baseline_full_analysis():
    client = MockDataClient(seed=42)
    bars = await client.get_bars("NVDA", "1d", limit=300)
    return await compute_full_analysis("NVDA", bars, "1d")


def _make_trace(*, fired: bool, score: int = 5) -> RuleTrace:
    h = RuleResult(
        name="H_test", rule_type=RuleType.HARD, passed=True, score=1, max_score=1
    )
    s = RuleResult(
        name="S_test", rule_type=RuleType.SOFT, passed=True, score=score, max_score=2
    )
    return RuleTrace(
        timestamp=datetime.now(UTC),
        ticker="NVDA",
        hard_rules=[h, h, h],
        soft_rules=[s, s, s],
        all_hard_passed=True,
        soft_score=score,
        soft_max_score=6,
        confidence_label="STRONG" if fired else "VETO",
        confidence_score=Decimal(score) / Decimal("6"),
        fired=fired,
        fire_decision_reason="all_hard_passed_soft_score_5"
        if fired
        else "no_soft_confirmation",
    )


async def test_persist_candidate_roundtrip(db_conn, baseline_full_analysis) -> None:
    fa = baseline_full_analysis
    assert fa.regime is not None
    candidate = EntryCandidate(
        ticker="NVDA",
        direction="long_call",
        strategy_name="long_options_momentum",
        rule_trace=_make_trace(fired=True),
        full_analysis=fa,
        options_analysis=None,
        regime=fa.regime,
        overrides_applied={"rsi_min": 60},
        confidence="STRONG",
        sizing_multiplier=Decimal("1.0"),
        max_premium=Decimal("500"),
        shortlist=None,
        timestamp=datetime.now(UTC),
    )
    cid = await persist_candidate(db_conn, candidate)
    assert cid > 0
    row = fetch_candidate(db_conn, cid)
    assert row is not None
    assert row["ticker"] == "NVDA"
    assert row["direction"] == "long_call"
    assert row["status"] == "pending"
    assert row["candidate_kind"] == "entry"
    assert row["strategy_name"] == "long_options_momentum"
    # JSON columns roundtrip
    assert row["rule_trace_json"] is not None
    assert row["regime_snapshot_json"] is not None
    assert row["full_analysis_json"] is not None
    assert row["options_analysis_json"] is None  # we passed None


async def test_persist_evaluation_with_candidate(db_conn, baseline_full_analysis) -> None:
    fa = baseline_full_analysis
    assert fa.regime is not None
    candidate = EntryCandidate(
        ticker="NVDA",
        direction="long_call",
        strategy_name="long_options_momentum",
        rule_trace=_make_trace(fired=True),
        full_analysis=fa,
        options_analysis=None,
        regime=fa.regime,
        confidence="STRONG",
        sizing_multiplier=Decimal("1.0"),
        max_premium=Decimal("500"),
        timestamp=datetime.now(UTC),
    )
    cid = await persist_candidate(db_conn, candidate)
    eval_id = await persist_evaluation(
        db_conn,
        ticker="NVDA",
        cycle_id="cyc1",
        rule_trace=candidate.rule_trace,
        full_analysis=fa,
        options_analysis=None,
        regime=fa.regime,
        candidate_id=cid,
    )
    assert eval_id > 0
    row = db_conn.execute(
        "SELECT candidate_id, fired, full_analysis_summary, regime_summary "
        "FROM scanner_evaluations WHERE id = ?",
        (eval_id,),
    ).fetchone()
    assert row["candidate_id"] == cid
    assert row["fired"] == 1
    assert row["full_analysis_summary"]
    assert row["regime_summary"]


async def test_persist_evaluation_without_candidate(db_conn, baseline_full_analysis) -> None:
    fa = baseline_full_analysis
    eval_id = await persist_evaluation(
        db_conn,
        ticker="AMD",
        cycle_id="cyc2",
        rule_trace=_make_trace(fired=False, score=0),
        full_analysis=fa,
        options_analysis=None,
        regime=fa.regime,
        candidate_id=None,
    )
    row = db_conn.execute(
        "SELECT candidate_id, fired FROM scanner_evaluations WHERE id = ?",
        (eval_id,),
    ).fetchone()
    assert row["candidate_id"] is None
    assert row["fired"] == 0


async def test_summary_fields_populated(db_conn, baseline_full_analysis) -> None:
    fa = baseline_full_analysis
    assert fa.regime is not None
    eval_id = await persist_evaluation(
        db_conn,
        ticker="NVDA",
        cycle_id="cyc3",
        rule_trace=_make_trace(fired=False),
        full_analysis=fa,
        options_analysis=None,
        regime=fa.regime,
        candidate_id=None,
    )
    row = db_conn.execute(
        "SELECT full_analysis_summary, regime_summary FROM scanner_evaluations "
        "WHERE id = ?",
        (eval_id,),
    ).fetchone()
    assert "RSI" in row["full_analysis_summary"]
    assert "NVDA" in row["regime_summary"]


async def test_rule_trace_json_roundtrips(db_conn, baseline_full_analysis) -> None:
    """The stored rule_trace_json must be deserializable back to RuleTrace."""
    fa = baseline_full_analysis
    trace = _make_trace(fired=True)
    eval_id = await persist_evaluation(
        db_conn,
        ticker="NVDA",
        cycle_id="cyc4",
        rule_trace=trace,
        full_analysis=fa,
        options_analysis=None,
        regime=fa.regime,
        candidate_id=None,
    )
    row = db_conn.execute(
        "SELECT rule_trace_json FROM scanner_evaluations WHERE id = ?",
        (eval_id,),
    ).fetchone()
    restored = RuleTrace.model_validate_json(row["rule_trace_json"])
    assert restored.ticker == "NVDA"
    assert restored.confidence_label == trace.confidence_label
    assert len(restored.hard_rules) == 3


async def test_fetch_recent_evaluations_filters_by_ticker(
    db_conn, baseline_full_analysis
) -> None:
    fa = baseline_full_analysis
    for ticker in ("NVDA", "AMD", "NVDA"):
        await persist_evaluation(
            db_conn,
            ticker=ticker,
            cycle_id="cyc5",
            rule_trace=_make_trace(fired=False),
            full_analysis=fa,
            options_analysis=None,
            regime=fa.regime,
            candidate_id=None,
        )
    rows_nvda = fetch_recent_evaluations(db_conn, ticker="NVDA")
    assert len(rows_nvda) == 2
    assert all(r["ticker"] == "NVDA" for r in rows_nvda)
