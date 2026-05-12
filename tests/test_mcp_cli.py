"""Phase 8.7: tests for the MCP admin CLI."""

from __future__ import annotations

import io
import sqlite3
from contextlib import redirect_stdout

import pytest

from services.mcp.cli import main
from shared.services.credentials import get_credential_record, get_credential_secrets
from shared.services.encryption import EncryptionService
from tests._api_helpers import reset_modules_for_test_db
from tests._credential_helpers import TEST_ENCRYPTION_KEY


@pytest.fixture
def db_with_env(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    return reset_modules_for_test_db(tmp_path, monkeypatch)  # type: ignore[no-any-return]


def test_generate_api_key_creates_credential(db_with_env: sqlite3.Connection) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["generate-api-key"])
    record = get_credential_record(db_with_env, "mcp_api_key")
    assert record is not None
    assert record.is_configured
    # Plaintext printed once to stdout
    assert "tnx_" in buf.getvalue()


def test_generate_twice_blocks_without_force(db_with_env: sqlite3.Connection) -> None:
    main(["generate-api-key"])
    with pytest.raises(SystemExit) as exc:
        main(["generate-api-key"])
    assert exc.value.code == 2


def test_rotate_replaces_existing_key(db_with_env: sqlite3.Connection) -> None:
    main(["generate-api-key"])
    enc = EncryptionService(TEST_ENCRYPTION_KEY)
    first = get_credential_secrets(db_with_env, enc, "mcp_api_key", use_cache=False)
    assert first is not None
    first_key = first["api_key"]
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["rotate-api-key"])
    second = get_credential_secrets(db_with_env, enc, "mcp_api_key", use_cache=False)
    assert second is not None
    assert second["api_key"] != first_key
    assert "ROTATED" in buf.getvalue()


def test_revoke_removes_credential(db_with_env: sqlite3.Connection) -> None:
    main(["generate-api-key"])
    main(["revoke-api-key"])
    record = get_credential_record(db_with_env, "mcp_api_key")
    assert record is None or not record.is_configured


def test_show_status_reports_unconfigured(db_with_env: sqlite3.Connection) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["show-status"])
    assert '"configured": false' in buf.getvalue()


def test_show_status_reports_configured(db_with_env: sqlite3.Connection) -> None:
    main(["generate-api-key"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["show-status"])
    assert '"configured": true' in buf.getvalue()
