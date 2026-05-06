"""TradNex orchestrator CLI.

Examples:
    python -m services.orchestrator.cli process 1
    python -m services.orchestrator.cli process-pending
    python -m services.orchestrator.cli vetoes 1
    python -m services.orchestrator.cli calendar [--days 14]
    python -m services.orchestrator.cli refresh-calendar
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from services.orchestrator.persistence import (
    fetch_latest_veto_trace,
    fetch_pending_candidate_ids,
)
from services.orchestrator.process_candidate import process_candidate
from shared.clients.factory import make_halt_feed, make_market_data_client
from shared.config import settings
from shared.db import get_connection, run_migrations
from shared.services.calendar_service import CalendarService
from shared.strategy.vetoes.base import VetoContext, VetoSettings


def _build_calendar_client() -> Any:
    """Pick mock vs Finnhub based on FINNHUB_API_KEY presence."""
    from shared.clients.finnhub_calendar import FinnhubCalendarClient
    from shared.clients.mock_calendar import MockCalendarClient

    if settings.FINNHUB_API_KEY:
        return FinnhubCalendarClient(settings.FINNHUB_API_KEY)
    return MockCalendarClient()


async def _build_ctx(conn: Any) -> VetoContext:
    halt_feed = make_halt_feed(settings)
    return VetoContext(
        conn=conn,
        calendar_service=CalendarService(conn),
        halt_feed=halt_feed,
        settings=VetoSettings(),
        current_time_utc=datetime.now(UTC),
    )


def _serialize(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


def _print_json(obj: Any) -> None:
    print(json.dumps(_serialize(obj), indent=2, default=str))


async def _cmd_process(args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        ctx = await _build_ctx(conn)
        result = await process_candidate(args.candidate_id, ctx)
        if args.json:
            _print_json(result)
            return
        print(f"Candidate #{args.candidate_id}")
        print(f"  already_processed: {result.already_processed}")
        print(f"  new_status:        {result.new_status}")
        if result.veto_trace is not None:
            t = result.veto_trace
            print(f"  veto_set:          {t.veto_set}")
            print(f"  any_failed:        {t.any_failed}")
            if t.failed_veto_names:
                print(f"  failed:            {t.failed_veto_names}")
    finally:
        conn.close()


async def _cmd_process_pending(args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        ctx = await _build_ctx(conn)
        ids = fetch_pending_candidate_ids(conn, stale_seconds=0)
        for cid in ids:
            await process_candidate(cid, ctx)
        if args.json:
            _print_json({"processed": ids})
            return
        print(f"Processed {len(ids)} pending candidates: {ids}")
    finally:
        conn.close()


async def _cmd_vetoes(args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        row = fetch_latest_veto_trace(conn, args.candidate_id)
        if row is None:
            raise SystemExit(f"No veto trace for candidate #{args.candidate_id}")
        if args.json:
            _print_json(row)
            return
        trace = json.loads(row["trace_json"])
        print(f"Veto trace for candidate #{args.candidate_id}")
        print(f"  set: {trace['veto_set']}  any_failed: {trace['any_failed']}")
        if trace.get("failed_veto_names"):
            print(f"  failed: {trace['failed_veto_names']}")
        print()
        for r in trace["results"]:
            marker = "FAIL" if r["failed"] else "pass"
            print(f"  [{marker}] {r['name']}: {r['description']}")
            if r.get("failure_reason"):
                print(f"      reason: {r['failure_reason']}")
    finally:
        conn.close()


async def _cmd_calendar(args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        svc = CalendarService(conn)
        now = datetime.now(UTC)
        end = now + timedelta(days=args.days)
        events = await svc.get_events_in_window(now, end)
        if args.json:
            _print_json({"events": [e.model_dump(mode="json") for e in events]})
            return
        if not events:
            print(f"No cached events in next {args.days} days")
            return
        print(f"Cached calendar events ({len(events)} events, next {args.days} days)")
        for e in events:
            ticker_label = f" [{e.ticker}]" if e.ticker else ""
            print(
                f"  {e.event_datetime_utc.isoformat(timespec='minutes')}  "
                f"{e.event_type:<8}  impact={e.impact:<7}{ticker_label}  {e.event_name}"
            )
    finally:
        conn.close()


async def _cmd_refresh_calendar(args: argparse.Namespace) -> None:
    from services.data.calendar_refresh_task import refresh_calendar_cache
    from shared.services.universe import get_universe

    conn = get_connection()
    try:
        client = _build_calendar_client()
        universe = await get_universe(conn)
        econ_count, earn_count = await refresh_calendar_cache(client, conn, universe)
        if args.json:
            _print_json(
                {"economic_inserted": econ_count, "earnings_inserted": earn_count}
            )
            return
        print(
            f"Calendar refresh: {econ_count} economic + {earn_count} earnings "
            "events inserted/updated"
        )
    finally:
        conn.close()


_HANDLERS = {
    "process": _cmd_process,
    "process-pending": _cmd_process_pending,
    "vetoes": _cmd_vetoes,
    "calendar": _cmd_calendar,
    "refresh-calendar": _cmd_refresh_calendar,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="services.orchestrator.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_p = sub.add_parser("process", help="Run vetoes + transition for one candidate")
    p_p.add_argument("candidate_id", type=int)
    p_p.add_argument("--json", action="store_true")

    p_pp = sub.add_parser("process-pending", help="Process all pending candidates now")
    p_pp.add_argument("--json", action="store_true")

    p_v = sub.add_parser("vetoes", help="Show latest veto trace for a candidate")
    p_v.add_argument("candidate_id", type=int)
    p_v.add_argument("--json", action="store_true")

    p_c = sub.add_parser("calendar", help="List cached calendar events")
    p_c.add_argument("--days", type=int, default=14)
    p_c.add_argument("--json", action="store_true")

    p_r = sub.add_parser("refresh-calendar", help="Force calendar refresh now")
    p_r.add_argument("--json", action="store_true")

    return parser


async def _run(args: argparse.Namespace) -> None:
    run_migrations()
    if settings.DATA_CLIENT == "mock":
        from shared.clients.mock_market_data import MockDataClient

        client = make_market_data_client(settings)
        if isinstance(client, MockDataClient):
            client.seed_iv_history()
    await _HANDLERS[args.cmd](args)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
