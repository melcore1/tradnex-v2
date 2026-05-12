"""MCP server authentication.

Two accepted credentials for the ``/mcp`` JSON-RPC endpoint:

1. **Raw API key** — the ``tnx_…`` string from
   ``python -m services.mcp.cli generate-api-key``. Compared in constant
   time via :func:`hmac.compare_digest`.
2. **OAuth-issued JWT** — produced by ``POST /oauth/token`` after a
   successful client_credentials grant. JWT is signed with HMAC-SHA256 using
   the same stored API key as the signing secret, so verification needs no
   additional state.

Both paths converge on ``MCPApiKeyVerifier.verify_token`` which the FastMCP
``RequireAuthMiddleware`` invokes for every ``/mcp`` request.
"""

from __future__ import annotations

import hmac
import logging

from mcp.server.auth.provider import AccessToken, TokenVerifier

from services.mcp.deps import db_session, get_encryption_or_raise
from services.mcp.oauth_token import verify_jwt
from shared.services.credentials import get_credential_secrets

logger = logging.getLogger(__name__)


class MCPApiKeyVerifier(TokenVerifier):
    """Validate Bearer tokens against the stored ``mcp_api_key`` credential."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None
        try:
            stored_key = _load_stored_api_key()
        except Exception:
            logger.exception("Failed to load mcp_api_key from credentials store")
            return None
        if stored_key is None:
            return None

        # Path A — raw API key (legacy / CLI testing). Constant-time compare.
        if hmac.compare_digest(token, stored_key):
            return AccessToken(
                token=token,
                client_id="tradnex-mcp-direct",
                scopes=["analytics:read"],
            )

        # Path B — JWT issued by /oauth/token, signed with the stored key.
        claims = verify_jwt(token, stored_key)
        if claims is None:
            return None
        scopes = claims.get("scope", "analytics:read").split()
        return AccessToken(
            token=token,
            client_id=str(claims.get("client_id", "tradnex-mcp")),
            scopes=scopes,
            expires_at=int(claims.get("exp", 0)) or None,
        )


def load_stored_api_key() -> str | None:
    """Public accessor for the token endpoint to validate client_secret."""
    return _load_stored_api_key()


def _load_stored_api_key() -> str | None:
    encryption = get_encryption_or_raise()
    with db_session() as conn:
        secrets = get_credential_secrets(conn, encryption, "mcp_api_key")
    if not secrets:
        return None
    api_key = secrets.get("api_key")
    if not isinstance(api_key, str) or not api_key:
        return None
    return api_key
