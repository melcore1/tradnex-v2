"""Claude subprocess wrapper.

Phase 5 invokes the Claude CLI as a subprocess (`claude -p <prompt>
--model <m> --max-turns 1`) per evaluation. Single-shot, single-turn,
deterministic.

Auth is ambient — the CLI uses the local `~/.claude/` session from the
user's Max subscription. We pass through HOME + PATH only; no other env
leaks into the subprocess.

Custom exceptions distinguish the failure modes:
  - ClaudeUnavailableError: subprocess didn't return a usable response
    (timeout, non-zero exit, auth failure). Caller falls back to rules.
  - ClaudeResponseInvalidError: returned but JSON malformed or schema
    mismatch. Caller persists the error and falls back to rules.
  - ClaudeRateLimitError: subclass of unavailable, signals back-off.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import BaseModel, ConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class ClaudeError(Exception):
    """Base for all Claude subprocess errors."""


class ClaudeUnavailableError(ClaudeError):
    """Subprocess timeout, auth failure, or non-zero exit."""


class ClaudeResponseInvalidError(ClaudeError):
    """Returned text isn't valid JSON or doesn't match expected schema."""


class ClaudeRateLimitError(ClaudeUnavailableError):
    """Detected as 'rate' / 'quota' in stderr; back off."""


class ClaudeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_text: str
    parsed_json: dict[str, Any]
    elapsed_ms: int
    model: str


_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?|\n?```\s*$", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    """Claude sometimes wraps JSON output in ```json ... ``` despite
    instructions. Strip any leading/trailing fences."""
    return _FENCE_RE.sub("", text).strip()


class ClaudeCliClient:
    """Real subprocess client for `claude -p`."""

    def __init__(
        self,
        *,
        model: str = "claude-opus-4-7",
        timeout_seconds: int = 90,
        max_turns: int = 1,
        cli_path: str = "claude",
    ) -> None:
        self._model = model
        self._timeout = timeout_seconds
        self._max_turns = max_turns
        self._cli_path = cli_path

    @property
    def model(self) -> str:
        return self._model

    async def evaluate(
        self,
        prompt: str,
        *,
        expected_schema: dict[str, Any] | None = None,
    ) -> ClaudeResponse:
        env = {
            "HOME": os.environ.get("HOME", "/root"),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        }
        t0 = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                self._cli_path,
                "-p",
                prompt,
                "--model",
                self._model,
                "--max-turns",
                str(self._max_turns),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(REPO_ROOT),
                env=env,
            )
        except FileNotFoundError as e:
            raise ClaudeUnavailableError(f"claude CLI not found: {e}") from e

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
        except TimeoutError as e:
            try:
                proc.kill()
                await proc.wait()
            except Exception:  # noqa: BLE001
                pass
            raise ClaudeUnavailableError("subprocess timeout") from e

        elapsed_ms = int((time.time() - t0) * 1000)

        if proc.returncode != 0:
            err = stderr.decode(errors="replace")[:500]
            if any(s in err.lower() for s in ("rate", "quota", "throttle")):
                raise ClaudeRateLimitError(err)
            raise ClaudeUnavailableError(
                f"claude exited {proc.returncode}: {err}"
            )

        raw_text = stdout.decode(errors="replace")
        cleaned = _strip_code_fences(raw_text)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ClaudeResponseInvalidError(
                f"bad JSON: {e}; first 200 chars: {cleaned[:200]}"
            ) from e

        if not isinstance(parsed, dict):
            raise ClaudeResponseInvalidError(
                f"expected JSON object, got {type(parsed).__name__}"
            )

        if expected_schema is not None:
            try:
                jsonschema.validate(parsed, expected_schema)
            except jsonschema.ValidationError as e:
                raise ClaudeResponseInvalidError(
                    f"schema mismatch: {e.message}"
                ) from e

        return ClaudeResponse(
            raw_text=raw_text,
            parsed_json=parsed,
            elapsed_ms=elapsed_ms,
            model=self._model,
        )

    async def health_check(self) -> bool:
        """Probe the CLI is reachable. Quick `--version`."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self._cli_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
            return proc.returncode == 0
        except (FileNotFoundError, TimeoutError):
            return False
