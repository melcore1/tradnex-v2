"""Tests for shared.clients.factory.make_market_data_client (Schwab path).

Phase 8a.5 changes the factory so that DATA_CLIENT=schwab reads creds from
the encrypted store and builds a tokens_provider closure. These tests cover
both happy paths and the missing-config error branches.
"""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shared.clients.factory import (
    DataClientNotConfigured,
    make_market_data_client,
)
from shared.clients.mock_market_data import MockDataClient
from shared.services.credentials import clear_cache, upsert_credential
from tests._credential_helpers import TEST_ENCRYPTION_KEY, get_test_encryption


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "factory.db"))
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("DATA_CLIENT", "mock")  # default for tests not exercising schwab
    from shared import config as cfg
    from shared import db as db_mod

    importlib.reload(cfg)
    importlib.reload(db_mod)
    db_mod.run_migrations()
    clear_cache()
    c = db_mod.get_connection()
    yield c
    c.close()


def test_mock_path_unchanged(conn) -> None:
    from shared.config import settings

    client = make_market_data_client(settings)
    assert isinstance(client, MockDataClient)


def test_schwab_path_auto_resolves_db_and_encryption(conn, monkeypatch) -> None:
    """Phase 8a.5 + fix: when called with just settings, factory pulls a
    fresh connection from shared.db and encryption from maybe_get_encryption.
    With no schwab_client seeded the call still surfaces a clear error."""
    monkeypatch.setenv("DATA_CLIENT", "schwab")
    from shared import config as cfg

    importlib.reload(cfg)
    with pytest.raises(DataClientNotConfigured, match="schwab_client"):
        make_market_data_client(cfg.settings)


def test_schwab_path_raises_when_encryption_key_missing(conn, monkeypatch) -> None:
    monkeypatch.setenv("DATA_CLIENT", "schwab")
    monkeypatch.setenv("ENCRYPTION_KEY", "")
    from shared import config as cfg

    importlib.reload(cfg)
    with pytest.raises(DataClientNotConfigured, match="ENCRYPTION_KEY"):
        make_market_data_client(cfg.settings)


def test_schwab_path_requires_schwab_client_credential(conn, monkeypatch) -> None:
    monkeypatch.setenv("DATA_CLIENT", "schwab")
    from shared import config as cfg

    importlib.reload(cfg)
    with pytest.raises(DataClientNotConfigured, match="schwab_client"):
        make_market_data_client(
            cfg.settings, db=conn, encryption=get_test_encryption()
        )


def test_schwab_path_uses_tokens_provider(conn, monkeypatch) -> None:
    """When everything is configured, factory builds a SchwabDataClient
    whose tokens_provider reads the latest schwab_oauth row from DB."""
    monkeypatch.setenv("DATA_CLIENT", "schwab")
    from shared import config as cfg

    importlib.reload(cfg)

    enc = get_test_encryption()
    upsert_credential(
        conn,
        enc,
        "schwab_client",
        secrets={"client_id": "cid", "client_secret": "csec"},
    )
    upsert_credential(
        conn,
        enc,
        "schwab_oauth",
        secrets={
            "access_token": "live_at",
            "refresh_token": "live_rt",
            "token_type": "Bearer",
            "scope": "",
        },
    )

    captured: dict[str, Any] = {}

    def fake_caf(
        api_key: str,
        app_secret: str,
        token_read_func: Any,
        token_write_func: Any,
        asyncio: bool = False,
        enforce_enums: bool = True,
    ) -> Any:
        captured["api_key"] = api_key
        captured["app_secret"] = app_secret
        captured["read_func"] = token_read_func
        captured["write_func"] = token_write_func
        captured["asyncio"] = asyncio
        return MagicMock()

    with patch(
        "schwab.auth.client_from_access_functions",
        side_effect=fake_caf,
    ):
        make_market_data_client(
            cfg.settings, db=conn, encryption=enc
        )

    assert captured["api_key"] == "cid"
    assert captured["app_secret"] == "csec"
    assert captured["asyncio"] is True
    # token_read_func returns wrapped {token: {...}, creation_timestamp: ...}
    wrapped = captured["read_func"]()
    assert wrapped["token"]["access_token"] == "live_at"
    assert wrapped["token"]["refresh_token"] == "live_rt"
    assert "creation_timestamp" in wrapped
