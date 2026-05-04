import importlib
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "migrations"


def test_imports() -> None:
    for mod in ["shared.config", "shared.db", "shared.events", "shared.schemas"]:
        importlib.import_module(mod)


def test_migrations_create_all_tables(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("ENVIRONMENT", "dev")
    from shared import config as config_mod
    importlib.reload(config_mod)
    from shared import db as db_mod
    importlib.reload(db_mod)

    applied = db_mod.run_migrations(MIGRATIONS_DIR)
    assert "0001_initial.sql" in applied
    assert "0002_watchlists.sql" in applied

    conn = sqlite3.connect(db_path)
    tables = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    expected = {
        "events",
        "candidates",
        "strategy_configs",
        "positions",
        "daily_iv_snapshots",
        "watchlists",
        "_migrations",
    }
    assert expected.issubset(tables)

    (count,) = conn.execute(
        "SELECT COUNT(*) FROM strategy_configs WHERE name='default'"
    ).fetchone()
    assert count == 1

    applied_again = db_mod.run_migrations(MIGRATIONS_DIR)
    assert applied_again == []


def test_event_round_trip(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    from shared import config as config_mod
    importlib.reload(config_mod)
    from shared import db as db_mod
    importlib.reload(db_mod)
    from shared import events as events_mod
    importlib.reload(events_mod)

    db_mod.run_migrations(MIGRATIONS_DIR)
    events_mod.emit("test", "info", "smoke", {"ok": True}, idempotency_key="k1")
    events_mod.emit("test", "info", "smoke", {"ok": True}, idempotency_key="k1")

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT service, event_type, idempotency_key FROM events"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0] == ("test", "smoke", "k1")


def test_candidate_round_trip(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    from shared import config as config_mod
    importlib.reload(config_mod)
    from shared import db as db_mod
    importlib.reload(db_mod)

    db_mod.run_migrations(MIGRATIONS_DIR)
    conn = db_mod.get_connection()
    conn.execute(
        "INSERT INTO candidates (ticker, direction, status, created_ts, updated_ts) "
        "VALUES (?, ?, ?, ?, ?)",
        ("AAPL", "long_call", "pending", 1.0, 1.0),
    )
    conn.commit()
    row = conn.execute(
        "SELECT ticker, direction, status FROM candidates"
    ).fetchone()
    assert tuple(row) == ("AAPL", "long_call", "pending")
