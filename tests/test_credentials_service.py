"""Tests for shared.services.credentials."""

from __future__ import annotations

import importlib

import pytest

from shared.services.credentials import (
    clear_cache,
    delete_credential,
    get_credential_record,
    get_credential_secrets,
    list_credential_records,
    upsert_credential,
)
from tests._credential_helpers import TEST_ENCRYPTION_KEY, get_test_encryption


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "creds.db"))
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


def test_upsert_then_read_record(conn) -> None:
    enc = get_test_encryption()
    record = upsert_credential(
        conn, enc, "finnhub", secrets={"api_key": "fk_test_123"}
    )
    assert record.credential_type == "finnhub"
    assert record.is_configured is True
    assert record.notes is None

    # Reading metadata never leaks secrets.
    metadata = get_credential_record(conn, "finnhub")
    assert metadata is not None
    assert metadata.is_configured is True
    assert "api_key" not in metadata.model_dump()


def test_secrets_decrypted_correctly(conn) -> None:
    enc = get_test_encryption()
    upsert_credential(
        conn, enc, "exa", secrets={"api_key": "ex_secret_xyz"}
    )
    secrets = get_credential_secrets(conn, enc, "exa")
    assert secrets == {"api_key": "ex_secret_xyz"}


def test_get_secrets_missing_returns_none(conn) -> None:
    enc = get_test_encryption()
    assert get_credential_secrets(conn, enc, "finnhub") is None


def test_upsert_replaces_existing(conn) -> None:
    enc = get_test_encryption()
    upsert_credential(conn, enc, "finnhub", secrets={"api_key": "v1"})
    upsert_credential(conn, enc, "finnhub", secrets={"api_key": "v2"})
    secrets = get_credential_secrets(conn, enc, "finnhub")
    assert secrets == {"api_key": "v2"}
    # Still exactly one row.
    rows = conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0]
    assert rows == 1


def test_delete_credential(conn) -> None:
    enc = get_test_encryption()
    upsert_credential(conn, enc, "finnhub", secrets={"api_key": "x"})
    assert delete_credential(conn, "finnhub") is True
    assert get_credential_record(conn, "finnhub") is None
    # Idempotent: second delete returns False, no exception.
    assert delete_credential(conn, "finnhub") is False


def test_cache_invalidated_on_upsert(conn) -> None:
    """Successive calls to get_credential_secrets serve from cache; an
    upsert should invalidate."""
    enc = get_test_encryption()
    upsert_credential(conn, enc, "finnhub", secrets={"api_key": "v1"})
    s1 = get_credential_secrets(conn, enc, "finnhub")
    upsert_credential(conn, enc, "finnhub", secrets={"api_key": "v2"})
    s2 = get_credential_secrets(conn, enc, "finnhub")
    assert s1 != s2
    assert s2 == {"api_key": "v2"}


def test_list_records_returns_metadata_only(conn) -> None:
    enc = get_test_encryption()
    upsert_credential(conn, enc, "finnhub", secrets={"api_key": "fk"})
    upsert_credential(
        conn, enc, "exa", secrets={"api_key": "ek"}, notes="news"
    )
    records = list_credential_records(conn)
    assert {r.credential_type for r in records} == {"finnhub", "exa"}
    for r in records:
        assert r.is_configured
        # No secret keys in any record.
        d = r.model_dump()
        assert "api_key" not in d
        assert "encrypted_data" not in d


def test_invalid_credential_type_rejected(conn) -> None:
    enc = get_test_encryption()
    with pytest.raises(ValueError, match="Unknown credential_type"):
        upsert_credential(conn, enc, "rogue_type", secrets={"x": "y"})  # type: ignore[arg-type]


def test_empty_secrets_rejected(conn) -> None:
    enc = get_test_encryption()
    with pytest.raises(ValueError, match="non-empty dict"):
        upsert_credential(conn, enc, "finnhub", secrets={})
