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


def test_metadata_lists_both_grants() -> None:
    md = build_metadata("https://scoutv2.meltradingmcp.uk")
    assert "authorization_code" in md["grant_types_supported"]
    assert "client_credentials" in md["grant_types_supported"]
    assert md["token_endpoint"].endswith("/oauth/token")
    assert md["authorization_endpoint"].endswith("/authorize")
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
                "grant_type": "password",  # not supported
                "username": "x",
                "password": "y",
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


# ---------- authorization_code grant + PKCE ----------


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for an S256 PKCE pair."""
    import base64
    import hashlib
    import secrets as _secrets

    verifier = _secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def test_authorize_redirects_with_code(db_with_env: sqlite3.Connection) -> None:
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    _verifier, challenge = _pkce_pair()
    app = _fresh_app()
    with TestClient(app) as client:
        resp = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "claude-ai",
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "xyz",
                "scope": "analytics:read",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://claude.ai/api/mcp/auth_callback?code=")
    assert "state=xyz" in location


def test_authorize_rejects_non_claude_redirect(db_with_env: sqlite3.Connection) -> None:
    app = _fresh_app()
    with TestClient(app) as client:
        resp = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "claude-ai",
                "redirect_uri": "https://attacker.example.com/steal",
                "code_challenge": "abc",
                "code_challenge_method": "S256",
                "state": "x",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 400
    assert "redirect_uri" in resp.json()["error_description"]


def test_authorize_rejects_missing_pkce(db_with_env: sqlite3.Connection) -> None:
    app = _fresh_app()
    with TestClient(app) as client:
        resp = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "claude-ai",
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "state": "x",
            },
            follow_redirects=False,
        )
    # Error redirected back to claude.ai with error= query param
    assert resp.status_code == 302
    assert "error=invalid_request" in resp.headers["location"]


def test_token_authorization_code_grant_round_trip(
    db_with_env: sqlite3.Connection,
) -> None:
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    verifier, challenge = _pkce_pair()
    app = _fresh_app()
    with TestClient(app) as client:
        # Step 1: /authorize → 302 with code
        authz = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "claude-ai",
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "abc",
            },
            follow_redirects=False,
        )
        assert authz.status_code == 302
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(authz.headers["location"]).query)
        code = qs["code"][0]

        # Step 2: /oauth/token exchanges code + verifier for JWT
        token = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "client_id": "claude-ai",
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            },
        )
    assert token.status_code == 200
    body = token.json()
    assert body["token_type"] == "Bearer"
    assert "access_token" in body


def test_token_authorization_code_rejects_wrong_verifier(
    db_with_env: sqlite3.Connection,
) -> None:
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    _real_verifier, challenge = _pkce_pair()
    app = _fresh_app()
    with TestClient(app) as client:
        authz = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "claude-ai",
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "x",
            },
            follow_redirects=False,
        )
        from urllib.parse import parse_qs, urlparse

        code = parse_qs(urlparse(authz.headers["location"]).query)["code"][0]
        token = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": "wrong_verifier_that_does_not_match",
                "client_id": "claude-ai",
            },
        )
    assert token.status_code == 400
    assert token.json()["error"] == "invalid_grant"


def test_token_authorization_code_is_single_use(
    db_with_env: sqlite3.Connection,
) -> None:
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    verifier, challenge = _pkce_pair()
    app = _fresh_app()
    with TestClient(app) as client:
        authz = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "claude-ai",
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "x",
            },
            follow_redirects=False,
        )
        from urllib.parse import parse_qs, urlparse

        code = parse_qs(urlparse(authz.headers["location"]).query)["code"][0]
        first = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "client_id": "claude-ai",
            },
        )
        assert first.status_code == 200
        # Replay must fail
        second = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "client_id": "claude-ai",
            },
        )
    assert second.status_code == 400
    assert second.json()["error"] == "invalid_grant"


def test_metadata_declares_auth_code_grant(db_with_env: sqlite3.Connection) -> None:
    app = _fresh_app()
    with TestClient(app) as client:
        resp = client.get("/.well-known/oauth-authorization-server")
    body = resp.json()
    assert "authorization_code" in body["grant_types_supported"]
    assert "client_credentials" in body["grant_types_supported"]
    assert "S256" in body["code_challenge_methods_supported"]
    assert body["authorization_endpoint"].endswith("/authorize")
