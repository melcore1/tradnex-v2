"""Bounded async queue for Claude evaluations.

The DB is the source of truth — `pending_llm_evaluation` rows are the
queue; the in-memory deque is just worker scheduling state. On restart,
bootstrap rehydrates from DB.

Atomic claim (`UPDATE … WHERE status='pending_llm_evaluation'` checking
`rowcount==1`) ensures concurrent workers (poller + immediate trigger +
queue worker) never double-process the same row.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from services.evaluator.evaluate import evaluate_candidate
from services.evaluator.persistence import claim_candidate_for_llm_eval
from shared.clients.claude_cli import ClaudeCliClient
from shared.clients.exa_news import ExaClient
from shared.clients.mock_claude_cli import MockClaudeCliClient
from shared.db import get_connection
from shared.events import emit
from shared.strategy.settings import EvaluatorSettings

SERVICE_NAME = "evaluator"


class EvaluationQueue:
    """Bounded concurrency, idempotent enqueue, atomic claim per worker."""

    def __init__(self, *, max_concurrent: int = 3) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._pending: deque[int] = deque()
        self._enqueued: set[int] = set()
        self._in_flight: set[int] = set()

    async def enqueue(self, candidate_id: int) -> None:
        if candidate_id in self._enqueued:
            return
        self._enqueued.add(candidate_id)
        self._pending.append(candidate_id)
        emit(
            SERVICE_NAME,
            "info",
            "queued",
            {
                "candidate_id": candidate_id,
                "depth": len(self._pending),
                "in_flight": len(self._in_flight),
            },
        )

    async def process_one(
        self,
        *,
        claude: ClaudeCliClient | MockClaudeCliClient,
        exa: ExaClient,
        cfg: EvaluatorSettings,
    ) -> bool:
        """Claim + evaluate the next pending candidate. Returns False when
        the queue is empty (caller can sleep)."""
        if not self._pending:
            return False
        candidate_id = self._pending.popleft()
        async with self._semaphore:
            self._in_flight.add(candidate_id)
            try:
                claim_conn = get_connection()
                try:
                    claimed = await claim_candidate_for_llm_eval(
                        claim_conn, candidate_id
                    )
                finally:
                    claim_conn.close()
                if not claimed:
                    emit(
                        SERVICE_NAME,
                        "info",
                        "skip_already_claimed",
                        {"candidate_id": candidate_id},
                    )
                    return True
                worker_conn = get_connection()
                try:
                    await evaluate_candidate(
                        candidate_id, worker_conn, claude, exa, cfg
                    )
                finally:
                    worker_conn.close()
            except Exception as e:
                emit(
                    SERVICE_NAME,
                    "error",
                    "evaluate_exception",
                    {
                        "candidate_id": candidate_id,
                        "error": str(e)[:300],
                        "error_type": type(e).__name__,
                    },
                )
            finally:
                self._enqueued.discard(candidate_id)
                self._in_flight.discard(candidate_id)
        return True

    def status(self) -> dict[str, Any]:
        return {
            "depth": len(self._pending),
            "in_flight": len(self._in_flight),
            "enqueued_total": len(self._enqueued),
        }
