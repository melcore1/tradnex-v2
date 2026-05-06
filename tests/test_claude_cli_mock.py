"""MockClaudeCliClient tests."""

from __future__ import annotations

import pytest

from shared.clients.claude_cli import (
    ClaudeRateLimitError,
    ClaudeResponseInvalidError,
    ClaudeUnavailableError,
)
from shared.clients.mock_claude_cli import MockClaudeCliClient


@pytest.mark.asyncio
async def test_inject_canned_response_by_pattern() -> None:
    client = MockClaudeCliClient()
    client.inject_response(
        "AAPL", {"decision": "STRONG", "reasoning": "good earnings"}
    )
    response = await client.evaluate("evaluate AAPL with regime bull")
    assert response.parsed_json["decision"] == "STRONG"


@pytest.mark.asyncio
async def test_inject_default_response_for_unmatched() -> None:
    client = MockClaudeCliClient()
    client.inject_default_response(
        {"decision": "WEAK", "reasoning": "default response"}
    )
    response = await client.evaluate("anything goes")
    assert response.parsed_json["decision"] == "WEAK"


@pytest.mark.asyncio
async def test_inject_error_raises_specified_type() -> None:
    client = MockClaudeCliClient()
    client.inject_error(ClaudeRateLimitError)
    with pytest.raises(ClaudeRateLimitError):
        await client.evaluate("anything")


@pytest.mark.asyncio
async def test_call_log_records_prompts() -> None:
    client = MockClaudeCliClient(default_response={"decision": "WEAK", "reasoning": "x"})
    await client.evaluate("first prompt")
    await client.evaluate("second prompt")
    log = client.get_call_log()
    assert log == ["first prompt", "second prompt"]


@pytest.mark.asyncio
async def test_schema_validation_rejects_bad_response() -> None:
    client = MockClaudeCliClient()
    client.inject_default_response({"foo": "bar"})  # missing required 'decision'
    schema = {
        "type": "object",
        "required": ["decision", "reasoning"],
        "properties": {
            "decision": {"type": "string", "enum": ["STRONG", "VETO"]},
            "reasoning": {"type": "string"},
        },
    }
    with pytest.raises(ClaudeResponseInvalidError):
        await client.evaluate("anything", expected_schema=schema)


@pytest.mark.asyncio
async def test_no_match_no_default_raises() -> None:
    client = MockClaudeCliClient()
    with pytest.raises(ClaudeUnavailableError):
        await client.evaluate("orphan prompt")
