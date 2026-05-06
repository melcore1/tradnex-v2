"""Runtime toggles persisted in `strategy_configs.settings_json`.

Phase 6 unifies system on/off switches under a single source of truth so
the API's `/api/system/toggle` endpoint can flip them and every reader
respects the change on the next cycle (evaluator), next request
(scanner V1 veto) or next monitor tick.

Canonical keys:
  paused          (bool, default False) — scanner pause (Phase 4 V1 veto)
  monitor_paused  (bool, default False) — monitor cycle skip
  llm_enabled     (bool, default True ) — Claude evaluator on/off
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

DEFAULTS: dict[str, Any] = {
    "paused": False,
    "monitor_paused": False,
    "llm_enabled": True,
}


def get_toggles(conn: sqlite3.Connection) -> dict[str, Any]:
    """Read the active strategy_configs row's settings_json. Returns the
    full dict (so callers can pull non-toggle keys like `universe`).
    Unknown keys are passed through; missing keys aren't filled."""
    row = conn.execute(
        "SELECT settings_json FROM strategy_configs "
        "WHERE name = 'default' AND is_active = 1 LIMIT 1"
    ).fetchone()
    if row is None or not row["settings_json"]:
        return {}
    try:
        return dict(json.loads(row["settings_json"]))
    except (json.JSONDecodeError, TypeError):
        return {}


def get_toggle(
    conn: sqlite3.Connection,
    key: str,
    default: Any = None,
) -> Any:
    """Convenience: read a single toggle. If `default` is None, falls back
    to DEFAULTS[key] when known, else None."""
    cfg = get_toggles(conn)
    if key in cfg:
        return cfg[key]
    if default is not None:
        return default
    return DEFAULTS.get(key)


def set_toggle(
    conn: sqlite3.Connection,
    key: str,
    value: Any,
) -> dict[str, Any]:
    """Update a single key in settings_json and return the new full dict."""
    cfg = get_toggles(conn)
    cfg[key] = value
    conn.execute(
        "UPDATE strategy_configs SET settings_json = ?, updated_ts = ? "
        "WHERE name = 'default' AND is_active = 1",
        (json.dumps(cfg), time.time()),
    )
    conn.commit()
    return cfg


def set_toggles(
    conn: sqlite3.Connection,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Bulk-update multiple keys atomically. Returns the new full dict."""
    cfg = get_toggles(conn)
    cfg.update(updates)
    conn.execute(
        "UPDATE strategy_configs SET settings_json = ?, updated_ts = ? "
        "WHERE name = 'default' AND is_active = 1",
        (json.dumps(cfg), time.time()),
    )
    conn.commit()
    return cfg
