import json
from datetime import UTC, datetime
from typing import Any, Literal

from shared.db import get_connection

LogLevel = Literal["info", "warn", "error", "critical"]


def emit(
    service: str,
    level: LogLevel,
    event_type: str,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> None:
    payload = payload or {}
    ts = datetime.now(UTC).timestamp()

    print(f"[{level}] {service} {event_type} {payload}", flush=True)

    payload_json = json.dumps(payload, default=str)
    conn = get_connection()
    try:
        if idempotency_key is not None:
            conn.execute(
                "INSERT OR IGNORE INTO events "
                "(service, level, event_type, payload, timestamp, idempotency_key) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (service, level, event_type, payload_json, ts, idempotency_key),
            )
        else:
            conn.execute(
                "INSERT INTO events "
                "(service, level, event_type, payload, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (service, level, event_type, payload_json, ts),
            )
        conn.commit()
    finally:
        conn.close()
