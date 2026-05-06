"""In-memory mock Claude client for tests + mock-mode dev.

Inject canned responses keyed by prompt-substring match, or set a default
for unmatched prompts. Inject errors to force failure paths. The call log
records every prompt seen so tests can assert what was sent.
"""

from __future__ import annotations

import json
from typing import Any

from shared.clients.claude_cli import (
    ClaudeError,
    ClaudeResponse,
    ClaudeResponseInvalidError,
    ClaudeUnavailableError,
)


class MockClaudeCliClient:
    """Test-friendly mock with prompt-pattern-keyed responses."""

    def __init__(
        self,
        *,
        model: str = "mock-claude",
        default_response: dict[str, Any] | None = None,
    ) -> None:
        self._model = model
        self._responses: list[tuple[str, dict[str, Any]]] = []
        self._default: dict[str, Any] | None = default_response
        self._error_queue: list[type[ClaudeError]] = []
        self._call_log: list[str] = []

    @property
    def model(self) -> str:
        return self._model

    def inject_response(
        self, prompt_pattern: str, response: dict[str, Any]
    ) -> None:
        """Add a substring-matched canned response. First-match wins."""
        self._responses.append((prompt_pattern, response))

    def inject_default_response(self, response: dict[str, Any]) -> None:
        """Response for prompts that don't match any inject_response pattern."""
        self._default = response

    def inject_error(self, error_type: type[ClaudeError]) -> None:
        """Force the next call to raise the given exception type."""
        self._error_queue.append(error_type)

    def get_call_log(self) -> list[str]:
        return list(self._call_log)

    async def evaluate(
        self,
        prompt: str,
        *,
        expected_schema: dict[str, Any] | None = None,
    ) -> ClaudeResponse:
        self._call_log.append(prompt)

        if self._error_queue:
            err_type = self._error_queue.pop(0)
            raise err_type(f"mock-injected {err_type.__name__}")

        # Find first matching pattern
        chosen: dict[str, Any] | None = None
        for pattern, response in self._responses:
            if pattern in prompt:
                chosen = response
                break
        if chosen is None:
            chosen = self._default

        if chosen is None:
            raise ClaudeUnavailableError(
                "mock has no response for prompt and no default set"
            )

        # Schema validation behaves like the real client
        if expected_schema is not None:
            try:
                import jsonschema
                jsonschema.validate(chosen, expected_schema)
            except jsonschema.ValidationError as e:
                raise ClaudeResponseInvalidError(
                    f"schema mismatch: {e.message}"
                ) from e

        return ClaudeResponse(
            raw_text=json.dumps(chosen),
            parsed_json=chosen,
            elapsed_ms=1,
            model=self._model,
        )

    async def health_check(self) -> bool:
        return True
