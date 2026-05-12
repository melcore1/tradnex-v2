"""position_check — list current open positions with their latest evaluation.

Reads the ``positions`` and ``monitor_evaluations`` tables directly. Sensitive
data — only authenticated MCP callers reach this tool (the SDK's bearer
middleware gates the JSON-RPC dispatch).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from services.mcp.deps import db_session
from services.mcp.formatters import _s
from shared.services.positions import get_open_positions


async def position_check() -> dict[str, Any]:
    """Return open positions with their latest monitor evaluation."""
    with db_session() as conn:
        positions = await get_open_positions(conn)
        if not positions:
            return {"positions": [], "count": 0, "note": "No open positions."}

        # Import here so the function is testable without monitor service
        # being imported at module-eager load time.
        from services.monitor.persistence import fetch_recent_monitor_evaluations

        formatted: list[dict[str, Any]] = []
        for pos in positions:
            latest_eval: dict[str, Any] | None = None
            if pos.id is not None:
                rows = fetch_recent_monitor_evaluations(
                    conn, position_id=pos.id, hours=72, limit=1
                )
                latest_eval = rows[0] if rows else None

            formatted.append(
                {
                    "position_id": pos.id,
                    "ticker": pos.ticker,
                    "contract": pos.contract_symbol,
                    "side": pos.side,
                    "quantity": pos.quantity,
                    "strategy": pos.strategy_name,
                    "entry_price": _s(pos.entry_price),
                    "entry_ts": datetime.fromtimestamp(pos.entry_ts, tz=UTC).isoformat(),
                    "entry_dte": pos.entry_dte,
                    "entry_delta": _s(pos.entry_delta),
                    "entry_iv": _s(pos.entry_iv),
                    "current_pnl_pct": (
                        _s(latest_eval["current_pnl_pct"])
                        if latest_eval and latest_eval.get("current_pnl_pct") is not None
                        else None
                    ),
                    "dte_remaining": (
                        latest_eval["dte_remaining"]
                        if latest_eval and latest_eval.get("dte_remaining") is not None
                        else None
                    ),
                    "signals_fired_count": (
                        latest_eval["signals_fired_count"]
                        if latest_eval and latest_eval.get("signals_fired_count") is not None
                        else 0
                    ),
                    "last_eval_ts": (
                        datetime.fromtimestamp(
                            latest_eval["timestamp"], tz=UTC
                        ).isoformat()
                        if latest_eval and latest_eval.get("timestamp") is not None
                        else None
                    ),
                }
            )

    return {"positions": formatted, "count": len(formatted)}
