"""Tests for the credential-aware factory functions in shared.clients.factory."""

from __future__ import annotations

import importlib

import pytest

from shared.clients.exa_news import ExaNewsClient
from shared.clients.factory import make_calendar_client, make_exa_client
from shared.clients.finnhub_calendar import FinnhubCalendarClient
from shared.clients.mock_calendar import MockCalendarClient
from shared.clients.mock_exa_news import MockExaClient
from shared.services.credentials import clear_cache
from tests._credential_helpers import (
    TEST_ENCRYPTION_KEY,
    get_test_encryption,
    seed_credential,
)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "fact.db"))
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("FINNHUB_API_KEY", "")
    monkeypatch.setenv("EXA_API_KEY", "")
    from shared import config as cfg
    from shared import db as db_mod

    importlib.reload(cfg)
    importlib.reload(db_mod)
    db_mod.run_migrations()
    clear_cache()
    c = db_mod.get_connection()
    yield c
    c.close()


def test_calendar_uses_db_credential_when_present(conn) -> None:
    from shared.config import settings

    seed_credential(conn, "finnhub", {"api_key": "from_db"})
    client = make_calendar_client(
        settings, conn=conn, encryption=get_test_encryption()
    )
    assert isinstance(client, FinnhubCalendarClient)


def test_calendar_falls_back_to_env_when_db_empty(conn, monkeypatch) -> None:
    """When no DB row exists, env (Settings.FINNHUB_API_KEY) is used as a
    Phase 8a fallback. This path goes away once 8b ships."""
    monkeypatch.setenv("FINNHUB_API_KEY", "from_env")
    from shared import config as cfg

    importlib.reload(cfg)

    client = make_calendar_client(
        cfg.settings, conn=conn, encryption=get_test_encryption()
    )
    assert isinstance(client, FinnhubCalendarClient)


def test_calendar_falls_back_to_mock_when_neither(conn) -> None:
    from shared.config import settings

    client = make_calendar_client(
        settings, conn=conn, encryption=get_test_encryption()
    )
    assert isinstance(client, MockCalendarClient)


def test_exa_uses_db_credential_when_present(conn) -> None:
    from shared.config import settings

    seed_credential(conn, "exa", {"api_key": "ex_from_db"})
    client = make_exa_client(
        settings, conn=conn, encryption=get_test_encryption()
    )
    assert isinstance(client, ExaNewsClient)


def test_exa_no_creds_returns_mock(conn) -> None:
    from shared.config import settings

    client = make_exa_client(
        settings, conn=conn, encryption=get_test_encryption()
    )
    assert isinstance(client, MockExaClient)


def test_calendar_no_conn_falls_back_to_env(monkeypatch) -> None:
    """Callers without a conn (legacy paths) just get the env-based
    behavior. No DB lookup happens."""
    monkeypatch.setenv("FINNHUB_API_KEY", "env_only")
    from shared import config as cfg

    importlib.reload(cfg)

    client = make_calendar_client(cfg.settings)
    assert isinstance(client, FinnhubCalendarClient)
