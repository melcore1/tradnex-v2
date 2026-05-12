"""Phase 8.7 follow-up: OAuth 2.1 client_credentials grant.

Tests the /oauth/token endpoint, the discovery metadata, and the JWT path
in MCPApiKeyVerifier.
"""

from __future__ import annotations

import importlib
import sqlite3
import time
from typing import Any

import jwt as pyjwt
import pytest
from starlette.testclient import TestClient

from services.mcp.oauth_token import (
    JWT_ALGORITHM,
    build_metadata,
    issue_jwt,
    verify_jwt,
)
from tests._api_helpers import reset_modules_for_test_db
from tests._credential_helpers import TEST_ENCRYPTION_KEY, seed_credential

REAL_KEY = "tnx_test_key_for_oauth_path_a_b_c_unit_tests"


@pytest.fixture
def db_with_env(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    return reset_modules_for_test_db(tmp_path, monkeypatch)  # type: ignore[no-any-return]


def _fresh_app() -> Any:
    import services.mcp.main as mcp_main

    importlib.reload(mcp_main)
    return mcp_main.app


# ---------- pure functions ----------


def test_issue_jwt_returns_oauth_token_response() -> None:
    body = issue_jwt(REAL_KEY, client_id="claude")
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    assert "access_token" in body
    assert body["scope"] == "analytics:read"


def test_verify_jwt_round_trip() -> None:
    body = issue_jwt(REAL_KEY, client_id="claude")
    claims = verify_jwt(body["access_token"], REAL_KEY)
    assert claims is not None
    assert claims["client_id"] == "claude"
    assert claims["iss"] == "tradnex-mcp"


def test_verify_jwt_rejects_tampered_token() -> None:
    body = issue_jwt(REAL_KEY, client_id="claude")
    tampered = body["access_token"][:-2] + "AA"
    assert verify_jwt(tampered, REAL_KEY) is None


def test_verify_jwt_rejects_wrong_signing_key() -> None:
    body = issue_jwt(REAL_KEY, client_id="claude")
    assert verify_jwt(body["access_token"], "different_key") is None


def test_verify_jwt_rejects_expired_token() -> None:
    # Mint a token with iat 2h ago and exp 1h ago.
    past = int(time.time()) - 7200
    expired = pyjwt.encode(
        {
            "iss": "tradnex-mcp",
            "sub": "claude",
            "client_id": "claude",
            "iat": past,
            "exp": past + 3600,
            "scope": "analytics:read",
        },
        REAL_KEY,
        algorithm=JWT_ALGORITHM,
    )
    assert verify_jwt(expired, REAL_KEY) is None


def test_metadata_lists_only_client_credentials() -> None:
    md = build_metadata("https://scoutv2.meltradingmcp.uk")
    assert md["grant_types_supported"] == ["client_credentials"]
    assert md["token_endpoint"].endswith("/oauth/token")
    assert "client_secret_post" in md["token_endpoint_auth_methods_supported"]


# ---------- /oauth/token endpoint ----------


def test_token_endpoint_returns_jwt_for_valid_secret(
    db_with_env: sqlite3.Connection,
) -> None:
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    app = _fresh_app()
    with TestClient(app) as client:
        resp = client.post(
            "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "claude",
                "client_secret": REAL_KEY,
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "Bearer"
    assert "access_token" in body


def test_token_endpoint_rejects_wrong_secret(
    db_with_env: sqlite3.Connection,
) -> None:
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    app = _fresh_app()
    with TestClient(app) as client:
        resp = client.post(
            "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "claude",
                "client_secret": "wrong-secret",
            },
        )
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_client"


def test_token_endpoint_rejects_unsupported_grant(
    db_with_env: sqlite3.Connection,
) -> None:
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    app = _fresh_app()
    with TestClient(app) as client:
        resp = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "claude",
                "code": "abc",
            },
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "unsupported_grant_type"


def test_token_endpoint_accepts_basic_auth(
    db_with_env: sqlite3.Connection,
) -> None:
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    app = _fresh_app()
    with TestClient(app) as client:
        resp = client.post(
            "/oauth/token",
            data={"grant_type": "client_credentials"},
            auth=("claude", REAL_KEY),
        )
    assert resp.status_code == 200


def test_token_endpoint_reports_unconfigured(
    db_with_env: sqlite3.Connection,
) -> None:
    # No mcp_api_key seeded — server should return 500 with a helpful error.
    # Clear the process-wide secrets cache so a prior seeded test in this
    # module doesn't leak its key through `get_credential_secrets`.
    from shared.services import credentials as cred_mod

    cred_mod._secrets_cache.clear()
    app = _fresh_app()
    with TestClient(app) as client:
        resp = client.post(
            "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "claude",
                "client_secret": "anything",
            },
        )
    assert resp.status_code == 500
    assert "generate-api-key" in resp.json()["error_description"]


def test_metadata_endpoint_is_unauthenticated(
    db_with_env: sqlite3.Connection,
) -> None:
    app = _fresh_app()
    with TestClient(app) as client:
        resp = client.get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_endpoint"].endswith("/oauth/token")


# ---------- verifier integration ----------


async def test_verifier_accepts_raw_api_key(
    db_with_env: sqlite3.Connection,
) -> None:
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    from services.mcp.auth import MCPApiKeyVerifier

    verifier = MCPApiKeyVerifier()
    result = await verifier.verify_token(REAL_KEY)
    assert result is not None
    assert result.client_id == "tradnex-mcp-direct"


async def test_verifier_accepts_jwt(db_with_env: sqlite3.Connection) -> None:
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    body = issue_jwt(REAL_KEY, client_id="claude-ai-web")
    from services.mcp.auth import MCPApiKeyVerifier

    verifier = MCPApiKeyVerifier()
    result = await verifier.verify_token(body["access_token"])
    assert result is not None
    assert result.client_id == "claude-ai-web"
    assert "analytics:read" in result.scopes


async def test_verifier_rejects_jwt_signed_by_other_key(
    db_with_env: sqlite3.Connection,
) -> None:
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    # JWT minted with a *different* key — must be rejected.
    body = issue_jwt("attacker_key", client_id="evil")
    from services.mcp.auth import MCPApiKeyVerifier

    verifier = MCPApiKeyVerifier()
    assert await verifier.verify_token(body["access_token"]) is None
