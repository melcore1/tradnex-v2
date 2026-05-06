"""Real ClaudeCliClient subprocess tests.

These are opt-in integration tests; they actually fork the local `claude`
CLI. CI runs them only when RUN_CLAUDE_INTEGRATION=1 is set.
"""

from __future__ import annotations

import os

import pytest

from shared.clients.claude_cli import (
    ClaudeCliClient,
    ClaudeUnavailableError,
)

INTEGRATION = os.environ.get("RUN_CLAUDE_INTEGRATION") == "1"


@pytest.mark.skipif(not INTEGRATION, reason="set RUN_CLAUDE_INTEGRATION=1 to run")
@pytest.mark.asyncio
async def test_real_claude_returns_valid_json() -> None:
    client = ClaudeCliClient(timeout_seconds=60)
    schema = {
        "type": "object",
        "required": ["echo"],
        "properties": {"echo": {"type": "string"}},
    }
    prompt = (
        "Return JSON only, no prose, no fences: "
        '{"echo": "ping"}'
    )
    response = await client.evaluate(prompt, expected_schema=schema)
    assert response.parsed_json.get("echo") == "ping"


@pytest.mark.skipif(not INTEGRATION, reason="set RUN_CLAUDE_INTEGRATION=1 to run")
@pytest.mark.asyncio
async def test_timeout_raises_unavailable() -> None:
    client = ClaudeCliClient(timeout_seconds=1)
    with pytest.raises(ClaudeUnavailableError):
        await client.evaluate(
            "Wait 5 seconds, then return JSON {\"x\": 1}"
        )


@pytest.mark.asyncio
async def test_missing_cli_path_raises_unavailable() -> None:
    """Always-on test: invoking a non-existent binary raises cleanly."""
    client = ClaudeCliClient(cli_path="/nonexistent/claude-binary-xyz")
    with pytest.raises(ClaudeUnavailableError):
        await client.evaluate("anything")
