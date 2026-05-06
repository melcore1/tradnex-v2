"""/api/events/stream — Server-Sent Events.

Tails the `events` table for new rows. The frontend opens the stream
once and stays connected; reconnection uses Last-Event-ID to resume.

Implementation: poll the events table every SSE_POLL_INTERVAL_SECONDS,
emit any rows with id > last seen. Single-user, low-volume — polling is
fine; Phase 8/9 can switch to async pub/sub if needed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

from services.api.deps import DB, CurrentUser
from shared.config import settings

router = APIRouter()


async def _event_generator(
    request: Request,
    last_id: int,
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE events. Note: each iteration opens its own connection so
    we don't hold a SQLite cursor across the long-lived stream — sqlite3
    isn't friendly to that pattern."""
    from shared.db import get_connection

    poll = settings.SSE_POLL_INTERVAL_SECONDS
    last_seen = last_id
    while True:
        if await request.is_disconnected():
            return

        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT id, service, level, event_type, payload, timestamp "
                "FROM events WHERE id > ? ORDER BY id ASC LIMIT 100",
                (last_seen,),
            ).fetchall()
        finally:
            conn.close()

        for r in rows:
            payload = json.loads(r["payload"]) if r["payload"] else {}
            yield {
                "event": r["event_type"],
                "id": str(r["id"]),
                "data": json.dumps(
                    {
                        "id": int(r["id"]),
                        "service": r["service"],
                        "level": r["level"],
                        "event_type": r["event_type"],
                        "payload": payload,
                        "timestamp": float(r["timestamp"]),
                    },
                    default=str,
                ),
            }
            last_seen = int(r["id"])

        await asyncio.sleep(poll)


@router.get("/stream")
async def stream(
    request: Request,
    db: DB,
    user: CurrentUser,
    since_id: int = Query(0, ge=0),
) -> EventSourceResponse:
    """Open an SSE stream of events. The cookie auth is enforced via
    middleware + the CurrentUser dependency. Pass `since_id` to resume."""
    last_event_id = request.headers.get("Last-Event-ID")
    if last_event_id:
        try:
            since_id = max(since_id, int(last_event_id))
        except ValueError:
            pass
    return EventSourceResponse(_event_generator(request, since_id))
