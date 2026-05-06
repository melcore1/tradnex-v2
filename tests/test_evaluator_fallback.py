"""Rule-based fallback path: behavior when LLM is bypassed."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from services.evaluator.fallback import run_fallback_evaluation
from services.evaluator.persistence import (
    claim_candidate_for_llm_eval,
    load_full_candidate,
)
from services.monitor.persistence import persist_exit_candidate
from services.scanner.persistence import persist_candidate
from shared.strategy.settings import EvaluatorSettings


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "fb.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


async def _seed_entry(conn) -> int:
    from tests.fixtures.strategy_fixtures import build_long_call_candidate

    cand = await build_long_call_candidate()
    cid = await persist_candidate(conn, cand)
    conn.execute(
        "UPDATE candidates SET status='pending_llm_evaluation' WHERE id=?",
        (cid,),
    )
    conn.commit()
    return cid


async def _seed_exit(conn, *, urgent: bool) -> int:
    from tests.fixtures.strategy_fixtures import build_exit_candidate

    conn.execute(
        "INSERT INTO positions (id, ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts, status) VALUES (1, 'NVDA', 'X', 'long', 1, 5.0, ?, 'open')",
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


async def test_entry_fallback_returns_pending_human(db_conn) -> None:
    cid = await _seed_entry(db_conn)
    await claim_candidate_for_llm_eval(db_conn, cid)
    cand = await load_full_candidate(db_conn, cid)
    cfg = EvaluatorSettings()
    result = await run_fallback_evaluation(
        db_conn, cid, cand, cfg=cfg, fallback_reason="llm_disabled"
    )
    assert result.fallback is True
    assert result.new_status == "pending_human_approval"
    # selected_contract written
    row = db_conn.execute(
        "SELECT selected_contract_json FROM candidates WHERE id=?", (cid,)
    ).fetchone()
    assert row["selected_contract_json"] is not None


async def test_exit_urgent_fallback_returns_close(db_conn) -> None:
    cid = await _seed_exit(db_conn, urgent=True)
    await claim_candidate_for_llm_eval(db_conn, cid)
    cand = await load_full_candidate(db_conn, cid)
    cfg = EvaluatorSettings()
    result = await run_fallback_evaluation(
        db_conn, cid, cand, cfg=cfg, fallback_reason="claude_unavailable:test"
    )
    assert result.decision == "CLOSE"
    assert result.new_status == "pending_human_approval"


async def test_exit_no_urgent_fallback_returns_hold(db_conn) -> None:
    cid = await _seed_exit(db_conn, urgent=False)
    await claim_candidate_for_llm_eval(db_conn, cid)
    cand = await load_full_candidate(db_conn, cid)
    cfg = EvaluatorSettings()
    result = await run_fallback_evaluation(
        db_conn, cid, cand, cfg=cfg, fallback_reason="claude_unavailable:test"
    )
    assert result.decision == "HOLD"
    assert result.new_status == "held"


async def test_fallback_persists_evaluation_row(db_conn) -> None:
    cid = await _seed_entry(db_conn)
    await claim_candidate_for_llm_eval(db_conn, cid)
    cand = await load_full_candidate(db_conn, cid)
    cfg = EvaluatorSettings()
    await run_fallback_evaluation(
        db_conn, cid, cand, cfg=cfg, fallback_reason="llm_disabled"
    )
    row = db_conn.execute(
        "SELECT fallback_used, fallback_reason, model_used FROM llm_evaluations "
        "WHERE candidate_id = ?",
        (cid,),
    ).fetchone()
    assert row["fallback_used"] == 1
    assert row["fallback_reason"] == "llm_disabled"
    assert row["model_used"] == "fallback"


async def test_exit_lifecycle_event_includes_fallback_flag(db_conn) -> None:
    cid = await _seed_exit(db_conn, urgent=True)
    await claim_candidate_for_llm_eval(db_conn, cid)
    cand = await load_full_candidate(db_conn, cid)
    cfg = EvaluatorSettings()
    await run_fallback_evaluation(
        db_conn, cid, cand, cfg=cfg, fallback_reason="claude_unavailable:test"
    )
    rows = db_conn.execute(
        "SELECT payload_json FROM position_lifecycle_events "
        "WHERE position_id = 1 AND event_type = 'claude_evaluated'"
    ).fetchall()
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["fallback"] is True
    assert "claude_unavailable" in payload["reason"]


async def test_fallback_uses_active_prompt_id(db_conn) -> None:
    """Fallback row references the currently active prompt version."""
    cid = await _seed_entry(db_conn)
    await claim_candidate_for_llm_eval(db_conn, cid)
    cand = await load_full_candidate(db_conn, cid)
    cfg = EvaluatorSettings()
    await run_fallback_evaluation(
        db_conn, cid, cand, cfg=cfg, fallback_reason="llm_disabled"
    )
    row = db_conn.execute(
        "SELECT prompt_version_id FROM llm_evaluations WHERE candidate_id=?",
        (cid,),
    ).fetchone()
    assert row["prompt_version_id"] is not None
    # Should match the seeded entry_evaluation v1.
    expected = db_conn.execute(
        "SELECT id FROM prompt_versions "
        "WHERE template_name='entry_evaluation' AND status='active'"
    ).fetchone()
    assert row["prompt_version_id"] == expected["id"]
