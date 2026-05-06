"""End-to-end exit evaluator behavior."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from shared.clients.mock_halt_feed import MockHaltFeed
from shared.clients.mock_market_data import MockDataClient
from shared.schemas.core import Position
from shared.strategy.exit_evaluator import evaluate_position_for_exit
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import ExitSignalSeverity


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ee.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


def _pos(*, entry: Decimal = Decimal("2.50"), contract_symbol: str | None = None) -> Position:
    # NVDA mock OCC symbol convention: pick a known one
    return Position(
        id=1,
        ticker="NVDA",
        contract_symbol=contract_symbol or "NVDA260515C00145000",
        side="long",
        quantity=1,
        entry_price=entry,
        entry_ts=0.0,
        status="open",
        entry_iv=Decimal("0.30"),
    )


async def test_contract_not_found_returns_urgent(db_conn) -> None:
    client = MockDataClient(seed=42)
    client.seed_iv_history()
    halt_feed = MockHaltFeed()
    pos = _pos(contract_symbol="DOES_NOT_EXIST")
    trace = await evaluate_position_for_exit(
        pos, client, halt_feed, db_conn, ExitSettings()
    )
    assert trace.urgent_count == 1
    assert trace.signals[0].name == "contract_not_found"
    assert trace.signals[0].severity == ExitSignalSeverity.URGENT
    assert trace.needs_claude is True


async def test_full_evaluator_returns_15_signals(db_conn) -> None:
    """Use a chain with a known symbol; pin via patch so the evaluator's
    re-fetch returns the same chain."""
    client = MockDataClient(seed=42)
    client.seed_iv_history()
    halt_feed = MockHaltFeed()
    chain = await client.get_options_chain("NVDA")
    contract = chain.contracts[len(chain.contracts) // 2]
    pos = Position(
        id=1, ticker="NVDA", contract_symbol=contract.symbol, side="long",
        quantity=1, entry_price=contract.mid, entry_ts=0.0, status="open",
        entry_iv=contract.iv,
    )
    with patch.object(client, "get_options_chain", AsyncMock(return_value=chain)):
        trace = await evaluate_position_for_exit(
            pos, client, halt_feed, db_conn, ExitSettings()
        )
    assert len(trace.signals) == 15


async def test_auto_close_path_when_pnl_above_threshold(db_conn) -> None:
    """Set entry_price very low so current pnl exceeds auto_close_profit_pct."""
    client = MockDataClient(seed=42)
    client.seed_iv_history()
    halt_feed = MockHaltFeed()
    chain = await client.get_options_chain("NVDA")
    contract = chain.contracts[len(chain.contracts) // 2]
    pos = Position(
        id=1, ticker="NVDA", contract_symbol=contract.symbol, side="long",
        quantity=1,
        entry_price=contract.mid * Decimal("0.5"),  # current = 2x → +100%
        entry_ts=0.0, status="open", entry_iv=contract.iv,
    )
    with patch.object(client, "get_options_chain", AsyncMock(return_value=chain)):
        trace = await evaluate_position_for_exit(
            pos, client, halt_feed, db_conn, ExitSettings()
        )
    assert trace.auto_close_triggered
    assert trace.auto_close_reason is not None
    assert not trace.needs_claude  # auto-close pre-empts claude


async def test_urgent_path_routes_to_claude(db_conn) -> None:
    """Set entry_price slightly above current so we hit stop-loss URGENT
    without triggering AUTO_CLOSE."""
    client = MockDataClient(seed=42)
    client.seed_iv_history()
    halt_feed = MockHaltFeed()
    chain = await client.get_options_chain("NVDA")
    contract = chain.contracts[len(chain.contracts) // 2]
    pos = Position(
        id=1, ticker="NVDA", contract_symbol=contract.symbol, side="long",
        quantity=1,
        entry_price=contract.mid * Decimal("1.4"),  # -28% loss
        entry_ts=0.0, status="open", entry_iv=contract.iv,
    )
    with patch.object(client, "get_options_chain", AsyncMock(return_value=chain)):
        trace = await evaluate_position_for_exit(
            pos, client, halt_feed, db_conn, ExitSettings()
        )
    assert not trace.auto_close_triggered
    assert trace.urgent_count >= 1
    assert trace.needs_claude is True


async def test_no_signals_fired_no_claude(db_conn) -> None:
    """Patch all signals to return INFO not-triggered."""
    from shared.strategy.exit_signals.base import (
        ExitSignal,
        ExitSignalCategory,
    )

    benign = ExitSignal(
        name="benign", category=ExitSignalCategory.PNL,
        severity=ExitSignalSeverity.INFO, triggered=False,
        description="benign", details={}, threshold_used={},
    )
    client = MockDataClient(seed=42)
    client.seed_iv_history()
    halt_feed = MockHaltFeed()
    chain = await client.get_options_chain("NVDA")
    contract = chain.contracts[len(chain.contracts) // 2]
    pos = Position(
        id=1, ticker="NVDA", contract_symbol=contract.symbol, side="long",
        quantity=1, entry_price=contract.mid, entry_ts=0.0, status="open",
        entry_iv=contract.iv,
    )
    chain_patch = patch.object(client, "get_options_chain", AsyncMock(return_value=chain))
    chain_patch.start()
    targets = [
        "shared.strategy.exit_evaluator.signal_take_profit",
        "shared.strategy.exit_evaluator.signal_stop_loss",
        "shared.strategy.exit_evaluator.signal_trailing_stop",
        "shared.strategy.exit_evaluator.signal_delta_too_high",
        "shared.strategy.exit_evaluator.signal_delta_too_low",
        "shared.strategy.exit_evaluator.signal_theta_acceleration",
        "shared.strategy.exit_evaluator.signal_vega_exposure",
        "shared.strategy.exit_evaluator.signal_charm_acceleration",
        "shared.strategy.exit_evaluator.signal_iv_crush",
        "shared.strategy.exit_evaluator.signal_iv_spike",
        "shared.strategy.exit_evaluator.signal_dte_critical",
        "shared.strategy.exit_evaluator.signal_friday_position_short_dte",
        "shared.strategy.exit_evaluator.signal_underlying_halted",
        "shared.strategy.exit_evaluator.signal_adverse_gap",
        "shared.strategy.exit_evaluator.signal_setup_invalidated",
    ]
    patches = [patch(t, return_value=benign) for t in targets]
    for p in patches:
        p.start()
    try:
        trace = await evaluate_position_for_exit(
            pos, client, halt_feed, db_conn, ExitSettings()
        )
    finally:
        for p in patches:
            p.stop()
        chain_patch.stop()
    assert trace.urgent_count == 0
    assert trace.warning_count == 0
    assert not trace.needs_claude
    assert not trace.auto_close_triggered


async def test_underlying_halted_routes_to_claude(db_conn) -> None:
    from datetime import UTC, datetime

    from shared.clients.halt_feed import Halt

    client = MockDataClient(seed=42)
    client.seed_iv_history()
    halt_feed = MockHaltFeed()
    halt_feed.inject_halt(Halt(
        ticker="NVDA",
        halt_time=datetime.now(UTC),
        halt_reason="Volatility",
        halt_code="LUDP",
        is_active=True,
    ))
    chain = await client.get_options_chain("NVDA")
    contract = chain.contracts[len(chain.contracts) // 2]
    pos = Position(
        id=1, ticker="NVDA", contract_symbol=contract.symbol, side="long",
        quantity=1, entry_price=contract.mid, entry_ts=0.0, status="open",
        entry_iv=contract.iv,
    )
    with patch.object(client, "get_options_chain", AsyncMock(return_value=chain)):
        trace = await evaluate_position_for_exit(
            pos, client, halt_feed, db_conn, ExitSettings()
        )
    halt_signal = next(s for s in trace.signals if s.name == "underlying_halted")
    assert halt_signal.triggered
    assert halt_signal.severity == ExitSignalSeverity.URGENT
    assert trace.needs_claude or trace.auto_close_triggered
