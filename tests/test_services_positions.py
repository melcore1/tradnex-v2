"""shared/services/positions.py: CRUD + status transitions."""

from decimal import Decimal

import pytest

from shared.services.positions import (
    get_open_positions,
    get_position,
    update_position_status,
)


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sp.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


def _insert(conn, *, status: str = "open", entry_iv: float | None = 0.30) -> int:
    import time

    cur = conn.execute(
        "INSERT INTO positions (ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts, status, entry_iv) "
        "VALUES ('NVDA', 'X', 'long', 1, 2.50, ?, ?, ?)",
        (time.time(), status, entry_iv),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


async def test_get_open_positions_filters_by_status(db_conn) -> None:
    open_id = _insert(db_conn, status="open")
    closed_id = _insert(db_conn, status="closed")
    rows = await get_open_positions(db_conn)
    ids = {p.id for p in rows}
    assert open_id in ids
    assert closed_id not in ids


async def test_get_position_loads_extended_fields(db_conn) -> None:
    pid = _insert(db_conn, entry_iv=0.45)
    p = await get_position(db_conn, pid)
    assert p is not None
    assert p.entry_iv == Decimal("0.45")
    assert p.strategy_name == "long_options_momentum"


async def test_update_position_status_idempotent(db_conn) -> None:
    pid = _insert(db_conn, status="open")
    await update_position_status(db_conn, pid, "closed")
    await update_position_status(db_conn, pid, "closed")  # idempotent
    p = await get_position(db_conn, pid)
    assert p is not None
    assert p.status == "closed"


async def test_get_position_returns_none_when_missing(db_conn) -> None:
    p = await get_position(db_conn, 99999)
    assert p is None
