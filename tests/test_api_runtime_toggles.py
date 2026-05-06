"""Runtime toggles propagate to scanner/evaluator/monitor decision points."""

from __future__ import annotations

import pytest

from tests._api_helpers import build_test_client, reset_modules_for_test_db, seed_user


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    conn = reset_modules_for_test_db(tmp_path, monkeypatch)
    await seed_user(conn)
    client = build_test_client()
    client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpass1234"},
    )
    yield conn, client
    conn.close()


async def test_toggle_paused_visible_to_v1_veto(setup) -> None:
    """Setting `paused=True` via API makes V1 veto fire."""
    conn, client = setup
    client.post("/api/system/toggle", json={"name": "paused", "enabled": False})

    from datetime import UTC, datetime

    from shared.clients.mock_halt_feed import MockHaltFeed
    from shared.services.calendar_service import CalendarService
    from shared.strategy.vetoes.base import (
        OrchestratorCandidate,
        VetoContext,
        VetoSettings,
    )
    from shared.strategy.vetoes.entry import v1_strategy_paused

    cand = OrchestratorCandidate(
        id=1,
        candidate_kind="entry",
        ticker="NVDA",
        direction="long_call",
        status="pending",
        created_ts=datetime.now(UTC).timestamp(),
        position_id=None,
    )
    ctx = VetoContext(
        conn=conn,
        calendar_service=CalendarService(conn),
        halt_feed=MockHaltFeed(),
        settings=VetoSettings(),
        current_time_utc=datetime.now(UTC),
    )
    result = await v1_strategy_paused(cand, ctx)
    assert result.failed is True


async def test_llm_enabled_runtime_off_uses_fallback(setup) -> None:
    """Toggling llm_enabled=false makes evaluator skip Claude and run fallback."""
    conn, client = setup
    client.post(
        "/api/system/toggle",
        json={"name": "llm_enabled", "enabled": False},
    )

    from services.evaluator.evaluate import evaluate_candidate
    from services.evaluator.persistence import claim_candidate_for_llm_eval
    from services.scanner.persistence import persist_candidate
    from shared.clients.mock_claude_cli import MockClaudeCliClient
    from shared.clients.mock_exa_news import MockExaClient
    from shared.strategy.settings import EvaluatorSettings
    from tests.fixtures.strategy_fixtures import build_long_call_candidate

    cand = await build_long_call_candidate()
    cid = await persist_candidate(conn, cand)
    conn.execute(
        "UPDATE candidates SET status='pending_llm_evaluation' WHERE id=?", (cid,)
    )
    conn.commit()
    await claim_candidate_for_llm_eval(conn, cid)

    # Default-config has llm_enabled=True; runtime DB toggle should win.
    cfg = EvaluatorSettings()  # llm_enabled=True
    claude = MockClaudeCliClient()  # no canned response → would fail
    exa = MockExaClient(auto_seed=False)
    result = await evaluate_candidate(cid, conn, claude, exa, cfg)
    assert result.fallback is True
    assert result.fallback_reason == "llm_disabled"
    # No call to Claude
    assert claude.get_call_log() == []


async def test_monitor_paused_skips_cycle(setup) -> None:
    """Setting monitor_paused=True makes monitor cycle short-circuit."""
    conn, client = setup
    client.post(
        "/api/system/toggle",
        json={"name": "monitor_paused", "enabled": False},
    )

    import time as _t

    from services.monitor.cycle import run_monitor_cycle
    from shared.clients.mock_halt_feed import MockHaltFeed
    from shared.clients.mock_market_data import MockDataClient
    from shared.strategy.exit_settings import ExitSettings

    conn.execute(
        "INSERT INTO positions (ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts, status) VALUES "
        "('NVDA', 'NVDA250620C150', 'long', 1, 5.0, ?, 'open')",
        (_t.time() - 3600,),
    )
    conn.commit()
    result = await run_monitor_cycle(
        client=MockDataClient(seed=42),
        halt_feed=MockHaltFeed(),
        conn=conn,
        settings=ExitSettings(),
    )
    # When paused, no positions are evaluated regardless of count
    assert result.positions_evaluated == 0
