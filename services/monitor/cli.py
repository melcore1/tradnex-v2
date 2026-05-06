"""TradNex monitor CLI.

Examples:
    python -m services.monitor.cli monitor-now
    python -m services.monitor.cli evaluate-position 1
    python -m services.monitor.cli evaluations --hours 24
    python -m services.monitor.cli evaluations --position 1 --hours 24
    python -m services.monitor.cli lifecycle 1
    python -m services.monitor.cli open-positions
    python -m services.monitor.cli exit-candidates --status pending
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from services.monitor.cycle import evaluate_position, run_monitor_cycle
from services.monitor.persistence import (
    fetch_exit_candidates,
    fetch_recent_monitor_evaluations,
)
from shared.clients.factory import make_halt_feed, make_market_data_client
from shared.clients.halt_feed import HaltFeed
from shared.clients.market_data import MarketDataClient
from shared.clients.mock_market_data import MockDataClient
from shared.config import settings
from shared.db import get_connection, run_migrations
from shared.services.positions import (
    get_open_positions,
    get_position,
    get_position_lifecycle,
)
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals.base import ExitSignalSeverity, ExitSignalTrace


def _serialize(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


def _print_json(obj: Any) -> None:
    print(json.dumps(_serialize(obj), indent=2, default=str))


def _print_trace(trace: ExitSignalTrace) -> None:
    print(f"ExitSignalTrace pos={trace.position_id} ({trace.contract_symbol})")
    print(
        f"  P&L:        {trace.pnl_pct}% (${trace.pnl_dollars})  "
        f"entry={trace.entry_price}  current={trace.current_price}"
    )
    print(f"  DTE:        {trace.dte_remaining}  qty={trace.quantity}")
    if trace.auto_close_triggered:
        print(f"  AUTO_CLOSE: {trace.auto_close_reason}")
    print(
        f"  Signals:    {trace.urgent_count} urgent / "
        f"{trace.warning_count} warning / {trace.info_count} info "
        f"({len(trace.signals)} total)"
    )
    print(f"  Routing:    needs_claude={trace.needs_claude}")
    print()
    for s in trace.signals:
        severity_label = {
            ExitSignalSeverity.AUTO_CLOSE: "AUTO_CLOSE",
            ExitSignalSeverity.URGENT: "URGENT    ",
            ExitSignalSeverity.WARNING: "WARNING   ",
            ExitSignalSeverity.INFO: "info      ",
        }[s.severity]
        marker = "*" if s.triggered else " "
        print(f"   {marker} [{severity_label}] {s.name}: {s.description}")


async def _cmd_monitor_now(
    client: MarketDataClient, halt_feed: HaltFeed, args: argparse.Namespace
) -> None:
    conn = get_connection()
    try:
        result = await run_monitor_cycle(client, halt_feed, conn, ExitSettings())
        if args.json:
            _print_json(result)
            return
        print(f"Monitor cycle {result.cycle_id}")
        print(f"  Positions evaluated: {result.positions_evaluated}")
        print(f"  Exit candidates created: {result.exit_candidates_created}")
        print(f"  Auto-closes triggered: {result.auto_closes_triggered}")
        print(f"  Errors: {len(result.errors)}")
        for err in result.errors:
            print(
                f"    - position {err['position_id']} ({err['ticker']}): "
                f"{err['error_type']}: {err['error']}"
            )
    finally:
        conn.close()


async def _cmd_evaluate_position(
    client: MarketDataClient, halt_feed: HaltFeed, args: argparse.Namespace
) -> None:
    conn = get_connection()
    try:
        position = await get_position(conn, args.position_id)
        if position is None:
            raise SystemExit(f"Position #{args.position_id} not found")
        cycle_id = "manual_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        trace, candidate_id = await evaluate_position(
            position, client, halt_feed, conn, ExitSettings(), cycle_id
        )
        if args.json:
            payload = {
                "cycle_id": cycle_id,
                "trace": trace.model_dump(mode="json"),
                "exit_candidate_id": candidate_id,
            }
            _print_json(payload)
            return
        _print_trace(trace)
        if candidate_id is not None:
            print(f"\n  → Exit candidate #{candidate_id} created")
    finally:
        conn.close()


async def _cmd_evaluations(
    _client: MarketDataClient, _halt_feed: HaltFeed, args: argparse.Namespace
) -> None:
    conn = get_connection()
    try:
        rows = fetch_recent_monitor_evaluations(
            conn, position_id=args.position, hours=args.hours
        )
        if args.json:
            _print_json({"evaluations": rows})
            return
        if not rows:
            print(f"No monitor evaluations in last {args.hours}h")
            return
        print(f"Recent monitor evaluations ({len(rows)} rows, last {args.hours}h)")
        for row in rows:
            ts = datetime.fromtimestamp(row["timestamp"], UTC).isoformat(
                timespec="seconds"
            )
            ac = "AUTO" if row["auto_close_triggered"] else "    "
            cand = row["exit_candidate_id"] or ""
            print(
                f"  {ts}  pos={row['position_id']:<3}  pnl={row['current_pnl_pct']:.2f}%  "
                f"dte={row['dte_remaining']}  fired={row['signals_fired_count']}  "
                f"{ac}  cand={cand}  cycle={row['cycle_id']}"
            )
    finally:
        conn.close()


async def _cmd_lifecycle(
    _client: MarketDataClient, _halt_feed: HaltFeed, args: argparse.Namespace
) -> None:
    conn = get_connection()
    try:
        events = await get_position_lifecycle(conn, args.position_id)
        if args.json:
            _print_json({"events": [e.model_dump(mode="json") for e in events]})
            return
        if not events:
            print(f"No lifecycle events for position #{args.position_id}")
            return
        print(f"Lifecycle for position #{args.position_id} ({len(events)} events, newest first)")
        for e in events:
            ts = datetime.fromtimestamp(e.timestamp, UTC).isoformat(timespec="seconds")
            cycle = f" cycle={e.cycle_id}" if e.cycle_id else ""
            print(f"  {ts}  {e.event_type:<24}{cycle}  payload={e.payload}")
    finally:
        conn.close()


async def _cmd_open_positions(
    _client: MarketDataClient, _halt_feed: HaltFeed, args: argparse.Namespace
) -> None:
    conn = get_connection()
    try:
        positions = await get_open_positions(conn)
        if args.json:
            _print_json({"positions": [p.model_dump(mode="json") for p in positions]})
            return
        if not positions:
            print("No open positions")
            return
        print(f"Open positions ({len(positions)})")
        for p in positions:
            print(
                f"  #{p.id:<3} {p.ticker:<6} {p.contract_symbol}  "
                f"qty={p.quantity}  entry={p.entry_price}  status={p.status}"
            )
    finally:
        conn.close()


async def _cmd_exit_candidates(
    _client: MarketDataClient, _halt_feed: HaltFeed, args: argparse.Namespace
) -> None:
    conn = get_connection()
    try:
        rows = fetch_exit_candidates(conn, status=args.status)
        if args.json:
            _print_json({"exit_candidates": rows})
            return
        if not rows:
            print("No exit candidates")
            return
        print(f"Exit candidates ({len(rows)})")
        for row in rows:
            ts = datetime.fromtimestamp(row["created_ts"], UTC).isoformat(
                timespec="seconds"
            )
            routing = json.loads(row["overrides_applied_json"] or "{}")
            tag = "AUTO_CLOSE" if routing.get("is_auto_close") else "needs_claude"
            print(
                f"  #{row['id']:<3} {ts}  pos={row['position_id']}  {row['ticker']:<6}  "
                f"status={row['status']:<8}  {tag}"
            )
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="services.monitor.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_mon = sub.add_parser("monitor-now", help="Run one monitor cycle now")
    p_mon.add_argument("--json", action="store_true")

    p_ev = sub.add_parser("evaluate-position", help="Evaluate one position manually")
    p_ev.add_argument("position_id", type=int)
    p_ev.add_argument("--json", action="store_true")

    p_evs = sub.add_parser("evaluations", help="Recent monitor evaluations")
    p_evs.add_argument("--position", type=int, default=None)
    p_evs.add_argument("--hours", type=int, default=24)
    p_evs.add_argument("--json", action="store_true")

    p_lc = sub.add_parser("lifecycle", help="Lifecycle event history for a position")
    p_lc.add_argument("position_id", type=int)
    p_lc.add_argument("--json", action="store_true")

    p_op = sub.add_parser("open-positions", help="Currently open positions")
    p_op.add_argument("--json", action="store_true")

    p_ec = sub.add_parser("exit-candidates", help="Exit candidates")
    p_ec.add_argument("--status", default=None)
    p_ec.add_argument("--json", action="store_true")

    return parser


_HANDLERS = {
    "monitor-now": _cmd_monitor_now,
    "evaluate-position": _cmd_evaluate_position,
    "evaluations": _cmd_evaluations,
    "lifecycle": _cmd_lifecycle,
    "open-positions": _cmd_open_positions,
    "exit-candidates": _cmd_exit_candidates,
}


async def _run(args: argparse.Namespace) -> None:
    run_migrations()
    client = make_market_data_client(settings)
    halt_feed = make_halt_feed(settings)
    if isinstance(client, MockDataClient):
        client.seed_iv_history()
    await _HANDLERS[args.cmd](client, halt_feed, args)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
