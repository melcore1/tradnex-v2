"""Tests for the import-schwab-token CLI command."""

from __future__ import annotations

import importlib
import json
import sys

import pytest

from services.api import cli as api_cli
from shared.services.credentials import clear_cache, get_credential_secrets
from tests._credential_helpers import TEST_ENCRYPTION_KEY, get_test_encryption


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    from shared import config as cfg
    from shared import db as db_mod

    importlib.reload(cfg)
    importlib.reload(db_mod)
    importlib.reload(api_cli)
    db_mod.run_migrations()
    clear_cache()
    return tmp_path


def _run_cli(argv: list[str], monkeypatch) -> int:
    monkeypatch.setattr(sys, "argv", ["cli"] + argv)
    try:
        api_cli.main()
        return 0
    except SystemExit as e:
        return int(e.code) if e.code is not None else 0


def test_import_valid_token_file(env, monkeypatch, capsys) -> None:
    token_file = env / "schwab_token.json"
    token_file.write_text(
        json.dumps(
            {
                "creation_timestamp": 1_700_000_000,
                "token": {
                    "access_token": "imported_access",
                    "refresh_token": "imported_refresh",
                    "token_type": "Bearer",
                    "scope": "trading",
                    "expires_in": 1800,
                },
            }
        )
    )

    rc = _run_cli(
        ["import-schwab-token", "--file", str(token_file)], monkeypatch
    )
    assert rc == 0

    from shared.db import get_connection

    conn = get_connection()
    try:
        secrets = get_credential_secrets(
            conn, get_test_encryption(), "schwab_oauth", use_cache=False
        )
    finally:
        conn.close()
    assert secrets is not None
    assert secrets["access_token"] == "imported_access"
    assert secrets["refresh_token"] == "imported_refresh"


def test_import_rejects_malformed_json(env, monkeypatch, capsys) -> None:
    token_file = env / "bad.json"
    token_file.write_text("{not valid json")
    rc = _run_cli(
        ["import-schwab-token", "--file", str(token_file)], monkeypatch
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "not valid JSON" in err


def test_import_rejects_missing_required_keys(env, monkeypatch, capsys) -> None:
    token_file = env / "shape.json"
    token_file.write_text(json.dumps({"token": {"access_token": "only_access"}}))
    rc = _run_cli(
        ["import-schwab-token", "--file", str(token_file)], monkeypatch
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "required keys" in err
