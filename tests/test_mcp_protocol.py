"""Phase 8.7: MCP server protocol-level smoke tests.

Verifies the FastMCP app registers exactly the seven expected tools, exposes
`/health` unauthenticated, and rejects calls without a Bearer token.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from starlette.testclient import TestClient


def _fresh_app() -> Any:
    """Reload services.mcp.main so each TestClient gets its own session manager."""
    import services.mcp.main as mcp_main

    importlib.reload(mcp_main)
    return mcp_main.app

EXPECTED_TOOLS = {
    "quick_check",
    "scout",
    "option_chain",
    "market_overview",
    "regime_check",
    "correlation_check",
    "position_check",
    "calendar_check",
}


async def test_tool_registration_matches_expected() -> None:
    from services.mcp.main import mcp

    tools = await mcp.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS


async def test_tool_schemas_have_descriptions() -> None:
    """Every tool must have a non-empty description (Claude.ai shows these)."""
    from services.mcp.main import mcp

    tools = await mcp.list_tools()
    for t in tools:
        assert t.description, f"tool {t.name} missing description"


def test_health_endpoint_is_unauthenticated() -> None:
    """The /health route bypasses Bearer auth (operator probe)."""
    app = _fresh_app()

    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_mcp_endpoint_requires_auth() -> None:
    """Hitting /mcp without a Bearer token returns 401 from the auth middleware."""
    app = _fresh_app()

    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
    # SDK returns 401 with a WWW-Authenticate header on missing bearer.
    assert resp.status_code == 401


def test_protected_resource_metadata_exposed() -> None:
    """RFC 9728 metadata endpoint advertises the resource server URL."""
    app = _fresh_app()

    with TestClient(app) as client:
        resp = client.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    body = resp.json()
    assert "resource" in body


@pytest.mark.parametrize(
    "tool_name,must_contain",
    [
        ("quick_check", ["ticker"]),
        ("scout", ["ticker", "days_history"]),
        ("market_overview", ["market_type"]),
        ("regime_check", ["ticker"]),
        ("correlation_check", ["ticker_a", "ticker_b"]),
        ("calendar_check", ["days_ahead"]),
    ],
)
async def test_tool_schema_includes_expected_params(
    tool_name: str, must_contain: list[str]
) -> None:
    from services.mcp.main import mcp

    tools = await mcp.list_tools()
    matching = next(t for t in tools if t.name == tool_name)
    properties = (matching.inputSchema or {}).get("properties", {})
    for p in must_contain:
        assert p in properties, f"{tool_name} missing param {p}"
