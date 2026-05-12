"""MCP server authentication.

Single shared Bearer token, persisted in the encrypted credentials store
under ``credential_type='mcp_api_key'``. The SDK's ``TokenVerifier`` interface
takes the token string and returns an ``AccessToken`` (or None to reject).

We compare with :func:`hmac.compare_digest` to keep the check constant-time
and avoid leaking the stored key via timing.
"""

from __future__ import annotations

import hmac
import logging

from mcp.server.auth.provider import AccessToken, TokenVerifier

from services.mcp.deps import db_session, get_encryption_or_raise
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
            # No key configured yet — server rejects all requests until the
            # operator runs `python -m services.mcp.cli generate-api-key`.
            return None
        if not hmac.compare_digest(token, stored_key):
            return None
        return AccessToken(
            token=token,
            client_id="tradnex-mcp",
            scopes=["analytics:read"],
        )


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
