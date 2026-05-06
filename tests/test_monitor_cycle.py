"""Monitor cycle behavior: persistence, errors, routing, flag handling."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from services.monitor.cycle import run_monitor_cycle
from shared.clients.mock_halt_feed import MockHaltFeed
from shared.clients.mock_market_data import MockDataClient
from shared.strategy.exit_settings import ExitSettings


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "mon.db"))
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


@pytest.fixture
def halt_feed():
    return MockHaltFeed()


def _insert_position(
    conn,
    *,
    ticker: str = "NVDA",
    contract_symbol: str | None = None,
    entry_price: Decimal = Decimal("2.50"),
    entry_iv: Decimal = Decimal("0.30"),
    status: str = "open",
) -> int:
    import time

    cur = conn.execute(
        "INSERT INTO positions (candidate_id, ticker, contract_symbol, side, "
        "quantity, entry_price, entry_ts, status, entry_iv, entry_delta, "
        "entry_dte, strategy_name) VALUES (NULL, ?, ?, 'long', 1, ?, ?, ?, ?, ?, ?, ?)",
        (
            ticker,
            contract_symbol or f"{ticker}260515C00145000",
            float(entry_price),
            time.time(),
            status,
            float(entry_iv),
            0.30,
            9,
            "long_options_momentum",
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


async def test_no_open_positions_skips(db_conn, client, halt_feed) -> None:
    result = await run_monitor_cycle(client, halt_feed, db_conn, ExitSettings())
    assert result.positions_evaluated == 0
    assert result.exit_candidates_created == 0
    rows = db_conn.execute(
        "SELECT event_type FROM events WHERE event_type = 'monitor_no_positions'"
    ).fetchall()
    assert len(rows) >= 1


async def test_healthy_positions_get_evaluations_only(db_conn, client, halt_feed) -> None:
    # A position with a real symbol so all 15 signals run; pin chain
    chain = await client.get_options_chain("NVDA")
    contract = chain.contracts[len(chain.contracts) // 2]
    pid = _insert_position(
        db_conn,
        contract_symbol=contract.symbol,
        entry_price=contract.mid,
        entry_iv=contract.iv,
    )
    with patch.object(client, "get_options_chain", AsyncMock(return_value=chain)):
        result = await run_monitor_cycle(client, halt_feed, db_conn, ExitSettings())
    assert result.positions_evaluated == 1
    eval_count = db_conn.execute(
        "SELECT COUNT(*) FROM monitor_evaluations WHERE position_id = ?",
        (pid,),
    ).fetchone()[0]
    assert eval_count == 1


async def test_auto_close_routes_correctly(db_conn, client, halt_feed) -> None:
    chain = await client.get_options_chain("NVDA")
    contract = chain.contracts[len(chain.contracts) // 2]
    pid = _insert_position(
        db_conn,
        contract_symbol=contract.symbol,
        entry_price=contract.mid * Decimal("0.5"),  # +100% pnl → AUTO_CLOSE
        entry_iv=contract.iv,
    )
    with patch.object(client, "get_options_chain", AsyncMock(return_value=chain)):
        result = await run_monitor_cycle(client, halt_feed, db_conn, ExitSettings())
    assert result.auto_closes_triggered == 1
    cand = db_conn.execute(
        "SELECT id, candidate_kind, position_id, overrides_applied_json "
        "FROM candidates WHERE position_id = ?",
        (pid,),
    ).fetchone()
    assert cand is not None
    assert cand["candidate_kind"] == "exit"
    import json

    routing = json.loads(cand["overrides_applied_json"])
    assert routing["is_auto_close"] is True
    # Lifecycle event
    rows = db_conn.execute(
        "SELECT event_type FROM position_lifecycle_events WHERE position_id = ?",
        (pid,),
    ).fetchall()
    types = {r["event_type"] for r in rows}
    assert "auto_close_triggered" in types


async def test_needs_claude_routes_correctly(db_conn, client, halt_feed) -> None:
    chain = await client.get_options_chain("NVDA")
    contract = chain.contracts[len(chain.contracts) // 2]
    pid = _insert_position(
        db_conn,
        contract_symbol=contract.symbol,
        entry_price=contract.mid * Decimal("1.4"),  # -28% loss → URGENT
        entry_iv=contract.iv,
    )
    with patch.object(client, "get_options_chain", AsyncMock(return_value=chain)):
        result = await run_monitor_cycle(client, halt_feed, db_conn, ExitSettings())
    assert result.exit_candidates_created == 1
    assert result.auto_closes_triggered == 0
    rows = db_conn.execute(
        "SELECT event_type FROM position_lifecycle_events WHERE position_id = ?",
        (pid,),
    ).fetchall()
    types = {r["event_type"] for r in rows}
    assert "exit_candidate_created" in types


async def test_per_position_error_skip_and_continue(db_conn, client, halt_feed) -> None:
    chain = await client.get_options_chain("NVDA")
    contract = chain.contracts[len(chain.contracts) // 2]
    _insert_position(
        db_conn,
        ticker="NVDA",
        contract_symbol=contract.symbol,
        entry_price=contract.mid,
        entry_iv=contract.iv,
    )
    _insert_position(
        db_conn,
        ticker="AMD",
        contract_symbol="AMD_BAD",
        entry_price=Decimal("1.00"),
    )

    original_get_quote = client.get_quote

    async def faulty(ticker: str):
        if ticker == "AMD":
            raise RuntimeError("boom")
        return await original_get_quote(ticker)

    with (
        patch.object(client, "get_quote", side_effect=faulty),
        patch.object(client, "get_options_chain", AsyncMock(return_value=chain)),
    ):
        result = await run_monitor_cycle(client, halt_feed, db_conn, ExitSettings())
    assert result.positions_evaluated == 1
    assert len(result.errors) == 1
    assert result.errors[0]["ticker"] == "AMD"
    error_events = db_conn.execute(
        "SELECT payload FROM events WHERE event_type = 'monitor_position_error'"
    ).fetchall()
    assert any("AMD" in row["payload"] for row in error_events)


async def test_cycle_id_propagates(db_conn, client, halt_feed) -> None:
    chain = await client.get_options_chain("NVDA")
    contract = chain.contracts[len(chain.contracts) // 2]
    _insert_position(
        db_conn,
        contract_symbol=contract.symbol,
        entry_price=contract.mid,
        entry_iv=contract.iv,
    )
    with patch.object(client, "get_options_chain", AsyncMock(return_value=chain)):
        result = await run_monitor_cycle(
            client, halt_feed, db_conn, ExitSettings(), cycle_id="custom-mc-1"
        )
    assert result.cycle_id == "custom-mc-1"
    rows = db_conn.execute(
        "SELECT DISTINCT cycle_id FROM monitor_evaluations"
    ).fetchall()
    assert {r["cycle_id"] for r in rows} == {"custom-mc-1"}


async def test_monitor_disabled_no_positions_skips(db_conn, client, halt_feed) -> None:
    settings = ExitSettings(monitor_enabled=False)
    result = await run_monitor_cycle(client, halt_feed, db_conn, settings)
    assert result.positions_evaluated == 0
    rows = db_conn.execute(
        "SELECT event_type FROM events WHERE event_type = 'monitor_disabled_no_positions'"
    ).fetchall()
    assert len(rows) >= 1


async def test_monitor_disabled_with_positions_runs_with_warning(
    db_conn, client, halt_feed
) -> None:
    """Safety override: flag false but positions exist → still runs."""
    chain = await client.get_options_chain("NVDA")
    contract = chain.contracts[len(chain.contracts) // 2]
    _insert_position(
        db_conn,
        contract_symbol=contract.symbol,
        entry_price=contract.mid,
        entry_iv=contract.iv,
    )
    settings = ExitSettings(monitor_enabled=False)
    with patch.object(client, "get_options_chain", AsyncMock(return_value=chain)):
        result = await run_monitor_cycle(client, halt_feed, db_conn, settings)
    assert result.positions_evaluated == 1
    rows = db_conn.execute(
        "SELECT event_type FROM events WHERE event_type = 'monitor_running_with_flag_off'"
    ).fetchall()
    assert len(rows) >= 1
