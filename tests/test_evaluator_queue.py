"""EvaluationQueue + atomic claim + bootstrap rehydration tests."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from services.evaluator.main import bootstrap_evaluator
from services.evaluator.persistence import (
    claim_candidate_for_llm_eval,
    fetch_pending_llm_candidate_ids,
    reset_stranded_processing,
)
from services.evaluator.queue import EvaluationQueue
from services.scanner.persistence import persist_candidate
from shared.clients.mock_claude_cli import MockClaudeCliClient
from shared.clients.mock_exa_news import MockExaClient
from shared.strategy.settings import EvaluatorSettings


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "evq.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


async def _seed_pending_entry(conn: sqlite3.Connection) -> int:
    from tests.fixtures.strategy_fixtures import build_long_call_candidate

    candidate = await build_long_call_candidate()
    cid = await persist_candidate(conn, candidate)
    conn.execute(
        "UPDATE candidates SET status = 'pending_llm_evaluation' WHERE id = ?",
        (cid,),
    )
    conn.commit()
    return cid


async def test_enqueue_idempotent(db_conn) -> None:
    queue = EvaluationQueue(max_concurrent=1)
    await queue.enqueue(1)
    await queue.enqueue(1)
    await queue.enqueue(1)
    assert queue.status()["depth"] == 1


async def test_status_reports_depth_and_in_flight(db_conn) -> None:
    queue = EvaluationQueue(max_concurrent=2)
    await queue.enqueue(7)
    await queue.enqueue(8)
    s = queue.status()
    assert s["depth"] == 2
    assert s["in_flight"] == 0


async def test_atomic_claim_wins_exactly_one(db_conn) -> None:
    cid = await _seed_pending_entry(db_conn)
    # Two parallel claims; one must win, one must lose.
    r1 = await claim_candidate_for_llm_eval(db_conn, cid)
    r2 = await claim_candidate_for_llm_eval(db_conn, cid)
    assert (r1, r2) == (True, False)
    row = db_conn.execute(
        "SELECT status FROM candidates WHERE id = ?", (cid,)
    ).fetchone()
    assert row["status"] == "processing_llm_evaluation"


async def test_claim_skips_non_pending(db_conn) -> None:
    cid = await _seed_pending_entry(db_conn)
    db_conn.execute(
        "UPDATE candidates SET status = 'rejected_by_llm' WHERE id = ?",
        (cid,),
    )
    db_conn.commit()
    claimed = await claim_candidate_for_llm_eval(db_conn, cid)
    assert claimed is False


async def test_reset_stranded_processing_reverts_rows(db_conn) -> None:
    cid = await _seed_pending_entry(db_conn)
    db_conn.execute(
        "UPDATE candidates SET status='processing_llm_evaluation' WHERE id=?",
        (cid,),
    )
    db_conn.commit()
    count = reset_stranded_processing(db_conn)
    assert count == 1
    row = db_conn.execute(
        "SELECT status FROM candidates WHERE id = ?", (cid,)
    ).fetchone()
    assert row["status"] == "pending_llm_evaluation"


async def test_bootstrap_rehydrates_pending(db_conn) -> None:
    cid = await _seed_pending_entry(db_conn)
    cfg = EvaluatorSettings()
    queue = await bootstrap_evaluator(cfg)
    assert cid in queue._pending  # in-memory deque populated
    assert queue.status()["depth"] >= 1


async def test_fetch_pending_orders_by_created_ts(db_conn) -> None:
    """When multiple pending exist, fetch returns them in created_ts order."""
    cid1 = await _seed_pending_entry(db_conn)
    # Force a small gap on created_ts.
    db_conn.execute(
        "UPDATE candidates SET created_ts = ? WHERE id = ?",
        (datetime.now(UTC).timestamp() - 100, cid1),
    )
    cid2 = await _seed_pending_entry(db_conn)
    db_conn.execute(
        "UPDATE candidates SET created_ts = ? WHERE id = ?",
        (datetime.now(UTC).timestamp() - 1, cid2),
    )
    db_conn.commit()
    ids = fetch_pending_llm_candidate_ids(db_conn)
    assert ids[0] == cid1
    assert ids[-1] == cid2


async def test_process_one_returns_false_when_empty(db_conn) -> None:
    queue = EvaluationQueue(max_concurrent=1)
    cfg = EvaluatorSettings()
    claude = MockClaudeCliClient()
    exa = MockExaClient(auto_seed=False)
    did_work = await queue.process_one(claude=claude, exa=exa, cfg=cfg)
    assert did_work is False


# Avoid unused-import warnings under ruff
_ = (asyncio, Decimal)
