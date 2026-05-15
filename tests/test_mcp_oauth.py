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
    # 30-day default lifetime — avoids the every-hour re-auth dance Claude.ai
    # was triggering on close-tab / cross-device cold starts with the prior
    # 1-hour TTL. Rotate `mcp_api_key` to invalidate outstanding JWTs early.
    assert body["expires_in"] == 60 * 60 * 24 * 30
    assert "access_token" in body
    assert body["scope"] == "analytics:read"


def test_issue_jwt_respects_explicit_lifetime() -> None:
    """Callers can still request a shorter lifetime (e.g. for CLI tests or
    one-off short-lived tokens)."""
    body = issue_jwt(REAL_KEY, client_id="claude", lifetime_seconds=300)
    assert body["expires_in"] == 300


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


def test_metadata_advertises_registration_endpoint() -> None:
    """RFC 7591 DCR — required for clients like Cherry Studio that refuse
    to start when registration_endpoint is missing. Existing Claude.ai
    flows ignore this field; they have a working client config already."""
    md = build_metadata("https://scoutv2.meltradingmcp.uk")
    assert md["registration_endpoint"].endswith("/register")


# ---------- /register endpoint (RFC 7591 DCR) ----------


def test_register_endpoint_mints_client_id(
    db_with_env: sqlite3.Connection,
) -> None:
    """DCR is stateless — every call returns a fresh client_id, no
    client_secret, PKCE-only (token_endpoint_auth_method=none)."""
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    app = _fresh_app()
    with TestClient(app) as client:
        resp = client.post(
            "/register",
            json={
                "client_name": "cherry-studio",
                "redirect_uris": ["http://localhost:5173/oauth/callback"],
            },
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["client_id"].startswith("tradnex-mcp-")
    assert body["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in body
    assert body["redirect_uris"] == ["http://localhost:5173/oauth/callback"]
    assert body["grant_types"] == ["authorization_code"]
    assert body["response_types"] == ["code"]


def test_register_endpoint_handles_empty_body(
    db_with_env: sqlite3.Connection,
) -> None:
    """Some clients POST with no body. Don't crash — return a usable
    client_id and an empty redirect_uris list."""
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    app = _fresh_app()
    with TestClient(app) as client:
        resp = client.post("/register")
    assert resp.status_code == 201
    body = resp.json()
    assert body["client_id"].startswith("tradnex-mcp-")
    assert body["redirect_uris"] == []
    assert body["client_name"] == "anonymous-mcp-client"


def test_register_endpoint_mints_unique_ids_per_call(
    db_with_env: sqlite3.Connection,
) -> None:
    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    app = _fresh_app()
    with TestClient(app) as client:
        a = client.post("/register", json={}).json()
        b = client.post("/register", json={}).json()
    assert a["client_id"] != b["client_id"]


def test_register_then_auth_code_flow_works_end_to_end(
    db_with_env: sqlite3.Connection,
) -> None:
    """Full Cherry Studio scenario: DCR → /authorize → /oauth/token.

    The minted client_id from /register is used by the subsequent
    auth_code grant; the JWT comes back signed with mcp_api_key as
    usual. No client_secret involved — PKCE is the actual check."""
    import base64
    import hashlib

    seed_credential(db_with_env, "mcp_api_key", {"api_key": REAL_KEY})  # type: ignore[arg-type]
    app = _fresh_app()

    # PKCE pair
    verifier = "verifier-for-cherry-studio-test-flow-of-correct-length"
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode("ascii")
    )

    with TestClient(app) as client:
        reg = client.post(
            "/register",
            json={
                "client_name": "cherry-studio",
                "redirect_uris": ["http://localhost:5173/oauth/callback"],
            },
        ).json()
        client_id = reg["client_id"]

        # /authorize returns a 302 with ?code=... — disable redirect follow.
        authz = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "http://localhost:5173/oauth/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "xyz",
            },
            follow_redirects=False,
        )
        assert authz.status_code == 302
        location = authz.headers["location"]
        # Extract code from "http://localhost:5173/oauth/callback?code=...&state=xyz"
        code = location.split("code=")[1].split("&")[0]

        token_resp = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:5173/oauth/callback",
            },
        )
    assert token_resp.status_code == 200
    body = token_resp.json()
    assert body["token_type"] == "Bearer"
    assert "access_token" in body
    # JWT must verify against the stored mcp_api_key
    claims = verify_jwt(body["access_token"], REAL_KEY)
    assert claims is not None
    assert claims["client_id"] == client_id


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
