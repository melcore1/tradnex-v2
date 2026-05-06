"""Tests for env→DB credential auto-migration."""

from __future__ import annotations

import importlib

import pytest

from shared.services.credentials import (
    clear_cache,
    get_credential_record,
    get_credential_secrets,
    migrate_env_credentials,
    upsert_credential,
)
from tests._credential_helpers import TEST_ENCRYPTION_KEY, get_test_encryption


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "mig.db"))
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    from shared import config as cfg
    from shared import db as db_mod

    importlib.reload(cfg)
    importlib.reload(db_mod)
    db_mod.run_migrations()
    clear_cache()
    c = db_mod.get_connection()
    yield c
    c.close()


def test_migration_inserts_when_env_set(conn) -> None:
    enc = get_test_encryption()
    migrated = migrate_env_credentials(
        conn,
        enc,
        env={"FINNHUB_API_KEY": "fk_env_value", "EXA_API_KEY": None},
    )
    assert migrated == ["finnhub"]
    record = get_credential_record(conn, "finnhub")
    assert record is not None
    assert record.is_configured
    secrets = get_credential_secrets(conn, enc, "finnhub")
    assert secrets == {"api_key": "fk_env_value"}


def test_migration_idempotent(conn) -> None:
    enc = get_test_encryption()
    env = {"FINNHUB_API_KEY": "fk_v1", "EXA_API_KEY": None}
    first = migrate_env_credentials(conn, enc, env=env)
    second = migrate_env_credentials(conn, enc, env=env)
    assert first == ["finnhub"]
    assert second == []
    rows = conn.execute(
        "SELECT COUNT(*) FROM credentials WHERE credential_type='finnhub'"
    ).fetchone()[0]
    assert rows == 1


def test_migration_skips_when_db_row_exists(conn) -> None:
    """Once a credential is configured via the UI, the env value is
    ignored — even if it differs from what's in the DB."""
    enc = get_test_encryption()
    upsert_credential(
        conn, enc, "finnhub", secrets={"api_key": "ui_provided"}
    )
    migrated = migrate_env_credentials(
        conn, enc, env={"FINNHUB_API_KEY": "env_value"}
    )
    assert migrated == []
    secrets = get_credential_secrets(conn, enc, "finnhub")
    assert secrets == {"api_key": "ui_provided"}


def test_migration_handles_no_env_values(conn) -> None:
    enc = get_test_encryption()
    migrated = migrate_env_credentials(
        conn, enc, env={"FINNHUB_API_KEY": None, "EXA_API_KEY": ""}
    )
    assert migrated == []
    assert get_credential_record(conn, "finnhub") is None
    assert get_credential_record(conn, "exa") is None
