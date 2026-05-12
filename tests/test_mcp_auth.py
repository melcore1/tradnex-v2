"""Phase 8.7: MCPApiKeyVerifier verifies the stored Bearer token.

Tests the auth verifier in isolation — full MCP protocol smoke is in
`test_mcp_protocol.py`. Each test resets the DB + ENCRYPTION_KEY so the
verifier's lazy lookup hits the right state.
"""

from __future__ import annotations

import pytest

from tests._api_helpers import reset_modules_for_test_db
from tests._credential_helpers import TEST_ENCRYPTION_KEY, seed_credential


@pytest.fixture
def db_with_env(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    return reset_modules_for_test_db(tmp_path, monkeypatch)


async def test_valid_token_returns_access_token(db_with_env: object) -> None:
    from services.mcp.auth import MCPApiKeyVerifier

    seed_credential(db_with_env, "mcp_api_key", {"api_key": "tnx_valid_token"})  # type: ignore[arg-type]
    verifier = MCPApiKeyVerifier()
    result = await verifier.verify_token("tnx_valid_token")
    assert result is not None
    assert result.client_id == "tradnex-mcp"
    assert "analytics:read" in result.scopes


async def test_wrong_token_returns_none(db_with_env: object) -> None:
    from services.mcp.auth import MCPApiKeyVerifier

    seed_credential(db_with_env, "mcp_api_key", {"api_key": "tnx_correct"})  # type: ignore[arg-type]
    verifier = MCPApiKeyVerifier()
    assert await verifier.verify_token("tnx_wrong") is None


async def test_no_credential_configured_returns_none(db_with_env: object) -> None:
    """When no mcp_api_key has been generated, all tokens are rejected."""
    from services.mcp.auth import MCPApiKeyVerifier

    verifier = MCPApiKeyVerifier()
    assert await verifier.verify_token("any-token") is None


async def test_empty_token_returns_none(db_with_env: object) -> None:
    from services.mcp.auth import MCPApiKeyVerifier

    seed_credential(db_with_env, "mcp_api_key", {"api_key": "tnx_valid"})  # type: ignore[arg-type]
    verifier = MCPApiKeyVerifier()
    assert await verifier.verify_token("") is None


async def test_token_check_uses_constant_time_compare(db_with_env: object) -> None:
    """Sanity check that the verifier rejects same-length but different tokens.

    Real timing-attack resistance comes from hmac.compare_digest under the
    hood; this test just exercises the path with two equal-length values.
    """
    from services.mcp.auth import MCPApiKeyVerifier

    real = "tnx_" + "a" * 32
    fake = "tnx_" + "b" * 32
    seed_credential(db_with_env, "mcp_api_key", {"api_key": real})  # type: ignore[arg-type]
    verifier = MCPApiKeyVerifier()
    assert await verifier.verify_token(real) is not None
    assert await verifier.verify_token(fake) is None
