"""Minimal OAuth 2.1 `client_credentials` grant for the MCP server.

Claude.ai's Web Custom Connector beta UI exposes ``OAuth Client ID`` and
``OAuth Client Secret`` fields and runs an OAuth 2.1 client_credentials grant
to obtain an access token, which it then sends as ``Authorization: Bearer
<token>`` on subsequent ``/mcp`` requests. To make Claude.ai's Web UI work
with our server, we expose two endpoints:

- ``GET /.well-known/oauth-authorization-server``  RFC 8414 metadata.
- ``POST /oauth/token``  ``grant_type=client_credentials`` token endpoint.

We treat the stored ``mcp_api_key`` credential as the static client secret.
Any ``client_id`` is accepted (single-user, single-secret deployment); only
the secret is verified. On success, we issue a JWT signed with HMAC-SHA256
using the same ``mcp_api_key`` as the signing key. ``MCPApiKeyVerifier``
validates these JWTs alongside raw API keys for backwards compat.

Token lifetime is 1 hour. Refresh tokens are NOT issued (Claude.ai re-runs
the grant when its cached access token expires).
"""

from __future__ import annotations

import time
from typing import Any

import jwt

JWT_ALGORITHM = "HS256"
JWT_LIFETIME_SECONDS = 3600  # 1 hour
TOKEN_TYPE = "Bearer"


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
        "token_endpoint": f"{base}/oauth/token",
        "grant_types_supported": ["client_credentials"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
        "response_types_supported": [],  # we don't do auth-code flow
        "scopes_supported": ["analytics:read"],
    }
