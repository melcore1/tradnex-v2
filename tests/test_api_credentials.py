"""/api/credentials tests — write-only secrets, metadata-only reads."""

from __future__ import annotations

import importlib

import pytest

from shared.services.credentials import clear_cache
from tests._api_helpers import (
    build_test_client,
    reset_modules_for_test_db,
    seed_user,
)
from tests._credential_helpers import TEST_ENCRYPTION_KEY


@pytest.fixture
async def client_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    conn = reset_modules_for_test_db(tmp_path, monkeypatch)
    # reset_modules_for_test_db reloads shared.config; reload again so the
    # ENCRYPTION_KEY env var is picked up.
    from shared import config as cfg

    importlib.reload(cfg)
    clear_cache()

    await seed_user(conn)
    client = build_test_client()
    client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpass1234"},
    )
    yield conn, client
    conn.close()


async def test_list_empty_when_nothing_configured(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/credentials")
    assert r.status_code == 200
    assert r.json() == []


async def test_put_then_get_returns_metadata_only(client_setup) -> None:
    _, client = client_setup
    r = client.put(
        "/api/credentials/finnhub",
        json={"secrets": {"api_key": "fk_test"}, "notes": "from test"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["credential_type"] == "finnhub"
    assert body["is_configured"] is True
    assert body["notes"] == "from test"
    # Crucially: the response NEVER includes the secret value.
    assert "api_key" not in body
    assert "secrets" not in body
    assert "encrypted_data" not in body

    # GET single returns the same metadata
    r2 = client.get("/api/credentials/finnhub")
    assert r2.status_code == 200
    assert r2.json()["is_configured"] is True
    assert "api_key" not in r2.json()


async def test_list_returns_all_configured(client_setup) -> None:
    _, client = client_setup
    client.put(
        "/api/credentials/finnhub", json={"secrets": {"api_key": "f"}}
    )
    client.put(
        "/api/credentials/exa", json={"secrets": {"api_key": "e"}}
    )
    r = client.get("/api/credentials")
    assert r.status_code == 200
    types = {c["credential_type"] for c in r.json()}
    assert types == {"finnhub", "exa"}


async def test_get_unknown_type_404(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/credentials/finnhub")
    assert r.status_code == 404


async def test_put_invalid_type_422(client_setup) -> None:
    _, client = client_setup
    r = client.put(
        "/api/credentials/rogue_type", json={"secrets": {"api_key": "x"}}
    )
    # Pydantic Literal validation → 422
    assert r.status_code == 422


async def test_put_empty_secrets_422(client_setup) -> None:
    _, client = client_setup
    r = client.put(
        "/api/credentials/finnhub", json={"secrets": {}}
    )
    assert r.status_code == 422


async def test_delete_removes_credential(client_setup) -> None:
    _, client = client_setup
    client.put("/api/credentials/finnhub", json={"secrets": {"api_key": "x"}})
    r = client.delete("/api/credentials/finnhub")
    assert r.status_code == 204
    assert client.get("/api/credentials/finnhub").status_code == 404


async def test_delete_missing_404(client_setup) -> None:
    _, client = client_setup
    r = client.delete("/api/credentials/finnhub")
    assert r.status_code == 404


async def test_unauthenticated_blocked(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    conn = reset_modules_for_test_db(tmp_path, monkeypatch)
    from shared import config as cfg

    importlib.reload(cfg)
    clear_cache()
    client = build_test_client()
    # No login.
    r = client.get("/api/credentials")
    assert r.status_code == 401
    conn.close()


async def test_secrets_round_trip_encryption(client_setup) -> None:
    """The actual stored value is the encrypted ciphertext, not the
    plaintext key. Verify by reading the DB row directly."""
    conn, client = client_setup
    client.put(
        "/api/credentials/exa",
        json={"secrets": {"api_key": "raw_secret_value"}},
    )
    row = conn.execute(
        "SELECT encrypted_data FROM credentials WHERE credential_type='exa'"
    ).fetchone()
    assert row is not None
    # Plaintext must not be embedded in the stored ciphertext.
    assert "raw_secret_value" not in row["encrypted_data"]
