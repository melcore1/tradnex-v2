"""Minimal OAuth 2.1 auth surface for the MCP server.

Claude.ai's Web Custom Connector beta runs the **authorization code + PKCE**
flow (per MCP spec 2025-11-25). The Web UI also takes an OAuth Client Secret
which we use as a *defense-in-depth* check on the ``/token`` exchange. So
the full surface we expose:

- ``GET /.well-known/oauth-authorization-server``  RFC 8414 metadata.
- ``GET /authorize``  issues an auth code after validating PKCE params.
- ``POST /oauth/token``  exchanges either:
    * ``grant_type=authorization_code`` + ``code`` + ``code_verifier``
      (Claude.ai's Web UI flow), or
    * ``grant_type=client_credentials`` + ``client_secret`` (direct API
      callers / curl testing).

Any ``client_id`` is accepted (single-user, single-secret deployment). The
``client_secret`` (for token-endpoint auth) must equal the stored
``mcp_api_key``. On success, we issue a JWT signed with HMAC-SHA256 using
the same ``mcp_api_key`` as the signing key. ``MCPApiKeyVerifier`` accepts
both these JWTs and raw API keys for backwards compat.

Auth codes are stored process-local with a 5-minute expiry; single-use. JWT
lifetime is 30 days. No refresh tokens — Claude.ai's connector cache evicts
its access token periodically (and on close-tab / new-device), and our prior
1-hour lifetime caused a full re-auth dance on essentially every cold start.
30 days is fine for a single-user trusted deployment: the JWT is signed with
``mcp_api_key`` and ``services.mcp.cli rotate-mcp-api-key`` invalidates every
outstanding token immediately. So we trade the re-auth tax for the cost of
"a leaked token lasts up to 30 days," which is mitigated by the user being
the only holder of the key + the token traveling over HTTPS (Cloudflare
Tunnel) end-to-end.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any

import jwt

JWT_ALGORITHM = "HS256"
JWT_LIFETIME_SECONDS = 60 * 60 * 24 * 30  # 30 days
TOKEN_TYPE = "Bearer"

AUTH_CODE_LIFETIME_SECONDS = 300  # 5 min
AUTH_CODE_BYTES = 32

# Process-local store for in-flight authorization codes. Single-process
# deployment, single user; codes expire in 5 min so the dict stays small.
_auth_codes: dict[str, dict[str, Any]] = {}


class OAuthTokenError(Exception):
    """Raised when the client_credentials grant cannot be honored."""

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


def issue_jwt(
    api_key: str,
    *,
    client_id: str,
    scopes: list[str] | None = None,
    lifetime_seconds: int = JWT_LIFETIME_SECONDS,
) -> dict[str, Any]:
    """Sign and return an OAuth 2.1 token response for the given client.

    Output matches RFC 6749 §5.1: ``{access_token, token_type, expires_in,
    scope}``. ``access_token`` is a JWT keyed by ``api_key``.
    """
    issued_at = int(time.time())
    expires_at = issued_at + lifetime_seconds
    scope_str = " ".join(scopes or ["analytics:read"])
    claims = {
        "iss": "tradnex-mcp",
        "sub": client_id,
        "client_id": client_id,
        "iat": issued_at,
        "exp": expires_at,
        "scope": scope_str,
    }
    token = jwt.encode(claims, api_key, algorithm=JWT_ALGORITHM)
    return {
        "access_token": token,
        "token_type": TOKEN_TYPE,
        "expires_in": lifetime_seconds,
        "scope": scope_str,
    }


def verify_jwt(token: str, api_key: str) -> dict[str, Any] | None:
    """Return decoded claims if the JWT is valid + signed by ``api_key``; else None."""
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            api_key,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
    except jwt.InvalidTokenError:
        return None
    if claims.get("iss") != "tradnex-mcp":
        return None
    return claims


def build_metadata(resource_url: str) -> dict[str, Any]:
    """RFC 8414 OAuth 2.1 authorization-server metadata."""
    base = resource_url.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "grant_types_supported": ["authorization_code", "client_credentials"],
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
            "none",  # PKCE-only callers (e.g. some MCP clients)
        ],
        "scopes_supported": ["analytics:read"],
    }


def issue_auth_code(
    *,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: str,
) -> str:
    """Mint a new auth code; store its PKCE state for later /token exchange."""
    code = secrets.token_urlsafe(AUTH_CODE_BYTES)
    _auth_codes[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "scope": scope,
        "expires_at": int(time.time()) + AUTH_CODE_LIFETIME_SECONDS,
    }
    return code


def consume_auth_code(code: str, code_verifier: str) -> dict[str, Any] | None:
    """Validate auth code + PKCE verifier; return stored metadata on success.

    Pops the code from the store on first call — one-time-use semantics.
    Returns None when the code is unknown, expired, or PKCE check fails.
    """
    data = _auth_codes.pop(code, None)
    if data is None:
        return None
    if data["expires_at"] < int(time.time()):
        return None
    if data["code_challenge_method"] != "S256":
        return None
    verifier_hash = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = (
        base64.urlsafe_b64encode(verifier_hash).rstrip(b"=").decode("ascii")
    )
    if not _consteq(expected, data["code_challenge"]):
        return None
    return data


def _consteq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a, b)


def reset_auth_code_store() -> None:
    """Test helper: clear the in-memory auth code store."""
    _auth_codes.clear()
