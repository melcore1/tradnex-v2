"""End-to-end evaluator flow tests against MockClaudeCliClient."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from services.evaluator.evaluate import evaluate_candidate
from services.evaluator.persistence import (
    claim_candidate_for_llm_eval,
    fetch_recent_evaluations,
)
from services.scanner.persistence import persist_candidate
from shared.clients.claude_cli import (
    ClaudeRateLimitError,
    ClaudeUnavailableError,
)
from shared.clients.mock_claude_cli import MockClaudeCliClient
from shared.clients.mock_exa_news import MockExaClient
from shared.strategy.settings import EvaluatorSettings


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ev.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


async def _seed_entry_pending(conn) -> int:
    from tests.fixtures.strategy_fixtures import build_long_call_candidate

    cand = await build_long_call_candidate()
    cid = await persist_candidate(conn, cand)
    conn.execute(
        "UPDATE candidates SET status='pending_llm_evaluation' WHERE id=?",
        (cid,),
    )
    conn.commit()
    return cid


async def _seed_exit_pending(conn, *, urgent: bool = True) -> int:
    """Persist an ExitCandidate row + position. Returns candidate id."""
    from services.monitor.persistence import persist_exit_candidate
    from tests.fixtures.strategy_fixtures import build_exit_candidate

    conn.execute(
        "INSERT INTO positions (id, ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts, status) VALUES (1, 'NVDA', 'NVDA250620C150', "
        "'long', 1, 5.0, ?, 'open')",
        (datetime.now(UTC).timestamp() - 3600,),
    )
    conn.commit()
    cand = build_exit_candidate(position_id=1, urgent_signal=urgent)
    cid = await persist_exit_candidate(conn, cand)
    conn.execute(
        "UPDATE candidates SET status='pending_llm_evaluation' WHERE id=?",
        (cid,),
    )
    conn.commit()
    return cid


async def _claim_and_evaluate(
    conn, cid: int, claude: MockClaudeCliClient, *, cfg: EvaluatorSettings | None = None
):
    cfg = cfg or EvaluatorSettings()
    exa = MockExaClient(auto_seed=False)
    claimed = await claim_candidate_for_llm_eval(conn, cid)
    assert claimed is True
    return await evaluate_candidate(cid, conn, claude, exa, cfg)


async def test_entry_strong_routes_to_pending_human(db_conn) -> None:
    cid = await _seed_entry_pending(db_conn)
    claude = MockClaudeCliClient(default_response={
        "decision": "STRONG",
        "confidence": 0.85,
        "reasoning": "Strong setup across all rules",
        "selected_contract": {"symbol": "NVDA250620C150"},
    })
    result = await _claim_and_evaluate(db_conn, cid, claude)
    assert result.new_status == "pending_human_approval"
    assert result.decision == "STRONG"
    row = db_conn.execute(
        "SELECT status, selected_contract_json FROM candidates WHERE id=?", (cid,)
    ).fetchone()
    assert row["status"] == "pending_human_approval"
    assert row["selected_contract_json"] is not None
    sel = json.loads(row["selected_contract_json"])
    assert sel["symbol"] == "NVDA250620C150"


async def test_entry_veto_routes_to_rejected_by_llm(db_conn) -> None:
    cid = await _seed_entry_pending(db_conn)
    claude = MockClaudeCliClient(default_response={
        "decision": "VETO",
        "reasoning": "macro headwinds",
    })
    result = await _claim_and_evaluate(db_conn, cid, claude)
    assert result.new_status == "rejected_by_llm"


async def test_exit_close_routes_to_pending_human(db_conn) -> None:
    cid = await _seed_exit_pending(db_conn)
    claude = MockClaudeCliClient(default_response={
        "decision": "CLOSE",
        "reasoning": "take profit",
    })
    result = await _claim_and_evaluate(db_conn, cid, claude)
    assert result.new_status == "pending_human_approval"
    # Lifecycle event recorded
    rows = db_conn.execute(
        "SELECT event_type, payload_json FROM position_lifecycle_events "
        "WHERE position_id = 1 AND event_type = 'claude_evaluated'"
    ).fetchall()
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["decision"] == "CLOSE"
    assert payload["fallback"] is False


async def test_exit_hold_routes_to_held_with_lifecycle(db_conn) -> None:
    cid = await _seed_exit_pending(db_conn, urgent=False)
    claude = MockClaudeCliClient(default_response={
        "decision": "HOLD",
        "reasoning": "thesis intact",
    })
    result = await _claim_and_evaluate(db_conn, cid, claude)
    assert result.new_status == "held"
    row = db_conn.execute(
        "SELECT status FROM candidates WHERE id=?", (cid,)
    ).fetchone()
    assert row["status"] == "held"


async def test_exit_close_partial_routes_to_pending_human(db_conn) -> None:
    cid = await _seed_exit_pending(db_conn)
    claude = MockClaudeCliClient(default_response={
        "decision": "CLOSE_PARTIAL",
        "quantity": 1,
        "reasoning": "scale out",
    })
    result = await _claim_and_evaluate(db_conn, cid, claude)
    assert result.new_status == "pending_human_approval"
    assert result.decision == "CLOSE_PARTIAL"


async def test_claude_unavailable_falls_back(db_conn) -> None:
    cid = await _seed_entry_pending(db_conn)
    claude = MockClaudeCliClient()
    claude.inject_error(ClaudeUnavailableError)
    result = await _claim_and_evaluate(db_conn, cid, claude)
    assert result.fallback is True
    assert "claude_unavailable" in (result.fallback_reason or "")
    assert result.new_status == "pending_human_approval"  # entry rule confidence
    rows = fetch_recent_evaluations(db_conn, candidate_id=cid)
    assert len(rows) == 1
    assert rows[0]["fallback_used"] == 1


async def test_invalid_response_falls_back(db_conn) -> None:
    cid = await _seed_entry_pending(db_conn)
    claude = MockClaudeCliClient(default_response={"foo": "bar"})  # missing required
    result = await _claim_and_evaluate(db_conn, cid, claude)
    assert result.fallback is True
    assert "invalid_response" in (result.fallback_reason or "")


async def test_rate_limit_treated_as_unavailable(db_conn) -> None:
    cid = await _seed_entry_pending(db_conn)
    claude = MockClaudeCliClient()
    claude.inject_error(ClaudeRateLimitError)
    result = await _claim_and_evaluate(db_conn, cid, claude)
    assert result.fallback is True


async def test_llm_disabled_runs_fallback(db_conn) -> None:
    cid = await _seed_entry_pending(db_conn)
    claude = MockClaudeCliClient()  # would error if called (no default)
    cfg = EvaluatorSettings(llm_enabled=False)
    result = await _claim_and_evaluate(db_conn, cid, claude, cfg=cfg)
    assert result.fallback is True
    assert result.fallback_reason == "llm_disabled"
    assert claude.get_call_log() == []


async def test_evaluation_row_complete(db_conn) -> None:
    cid = await _seed_entry_pending(db_conn)
    claude = MockClaudeCliClient(default_response={
        "decision": "MODERATE",
        "confidence": 0.7,
        "reasoning": "ok setup",
    })
    result = await _claim_and_evaluate(db_conn, cid, claude)
    row = db_conn.execute(
        "SELECT * FROM llm_evaluations WHERE id = ?", (result.eval_id,)
    ).fetchone()
    assert row["candidate_id"] == cid
    assert row["fallback_used"] == 0
    assert row["model_used"] == "mock-claude"
    assert row["decision"] == "MODERATE"
    assert row["confidence"] == pytest.approx(0.7)
    assert row["elapsed_ms"] >= 0


async def test_prompt_too_large_falls_back(db_conn) -> None:
    cid = await _seed_entry_pending(db_conn)
    claude = MockClaudeCliClient(default_response={"decision": "STRONG", "reasoning": "x"})
    cfg = EvaluatorSettings(prompt_token_budget=10)  # 40 chars budget
    result = await _claim_and_evaluate(db_conn, cid, claude, cfg=cfg)
    assert result.fallback is True
    assert "prompt_too_large" in (result.fallback_reason or "")


async def test_unknown_contract_symbol_doesnt_persist(db_conn) -> None:
    """Claude returns a symbol not in the shortlist — no contract persisted."""
    cid = await _seed_entry_pending(db_conn)
    claude = MockClaudeCliClient(default_response={
        "decision": "STRONG",
        "reasoning": "ok",
        "selected_contract": {"symbol": "FAKE_SYMBOL_NOT_IN_LIST"},
    })
    await _claim_and_evaluate(db_conn, cid, claude)
    row = db_conn.execute(
        "SELECT selected_contract_json FROM candidates WHERE id=?", (cid,)
    ).fetchone()
    assert row["selected_contract_json"] is None


_ = Decimal  # keep import
