"""TradNex scanner CLI.

Examples:
    python -m services.scanner.cli scan-now
    python -m services.scanner.cli scan-ticker NVDA
    python -m services.scanner.cli evaluations --hours 24
    python -m services.scanner.cli evaluations --ticker NVDA --hours 24
    python -m services.scanner.cli candidates --status pending
    python -m services.scanner.cli candidate 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from services.scanner.cycle import evaluate_ticker, run_scan_cycle
from services.scanner.persistence import (
    fetch_candidate,
    fetch_recent_candidates,
    fetch_recent_evaluations,
)
from shared.clients.factory import make_market_data_client
from shared.clients.market_data import MarketDataClient
from shared.clients.mock_market_data import MockDataClient
from shared.config import settings
from shared.db import get_connection, run_migrations
from shared.services.watchlist import get_active_watchlist
from shared.strategy.base import RuleTrace
from shared.strategy.long_options_momentum import LongOptionsMomentum


def _serialize(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


def _print_json(obj: Any) -> None:
    print(json.dumps(_serialize(obj), indent=2, default=str))


def _print_rule_trace(trace: RuleTrace) -> None:
    print(f"Trace for {trace.ticker} @ {trace.timestamp.isoformat()}")
    print(
        f"  Hard rules: {sum(1 for r in trace.hard_rules if r.passed)}/"
        f"{len(trace.hard_rules)} passed"
    )
    for r in trace.hard_rules:
        marker = "PASS" if r.passed else "FAIL"
        print(f"    [{marker}] {r.name}  details={r.details}")
        if not r.passed and r.failure_reason:
            print(f"        reason: {r.failure_reason}")
    print(
        f"  Soft rules: score {trace.soft_score}/{trace.soft_max_score}"
    )
    for r in trace.soft_rules:
        print(
            f"    [score {r.score}/{r.max_score}] {r.name}  details={r.details}"
        )
    print(f"  Confidence: {trace.confidence_label} ({trace.confidence_score})")
    print(f"  Fired: {trace.fired}  reason: {trace.fire_decision_reason}")


async def _cmd_scan_now(client: MarketDataClient, args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        strategy = LongOptionsMomentum()
        result = await run_scan_cycle(client, conn, strategy)
        if args.json:
            _print_json(result)
            return
        print(f"Scan cycle {result.cycle_id}")
        print(f"  Tickers evaluated: {result.tickers_evaluated}")
        print(f"  Candidates fired: {result.candidates_fired}")
        print(f"  Errors: {len(result.errors)}")
        for err in result.errors:
            print(f"    - {err['ticker']}: {err['error_type']}: {err['error']}")
    finally:
        conn.close()


async def _cmd_scan_ticker(client: MarketDataClient, args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        # Look up overrides from today's watchlist if present
        watchlist = await get_active_watchlist(conn)
        ticker = args.ticker.upper()
        overrides = watchlist.per_ticker_overrides.get(ticker, {})
        strategy = LongOptionsMomentum()
        cycle_id = "manual_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        if isinstance(client, MockDataClient):
            client.seed_iv_history()
        result = await evaluate_ticker(
            ticker=ticker,
            client=client,
            conn=conn,
            strategy=strategy,
            overrides=overrides,
            cycle_id=cycle_id,
        )
        if args.json:
            payload = {
                "ticker": result.ticker,
                "candidate_id": result.candidate_id,
                "candidate_fired": result.candidate is not None,
                "rule_trace": result.rule_trace.model_dump(mode="json"),
            }
            _print_json(payload)
            return
        _print_rule_trace(result.rule_trace)
        if overrides:
            print(f"  Overrides applied: {overrides}")
        if result.candidate is not None and result.candidate.shortlist:
            print(f"  Shortlist ({len(result.candidate.shortlist)} contracts):")
            for c in result.candidate.shortlist:
                print(
                    f"    {c.symbol}  dte={c.dte}  strike={c.strike}  "
                    f"delta={c.delta}  mid={c.mid}  oi*vol={int(c.open_interest)*int(c.volume)}"
                )
    finally:
        conn.close()


async def _cmd_evaluations(_client: MarketDataClient, args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        rows = fetch_recent_evaluations(
            conn,
            ticker=args.ticker,
            hours=args.hours,
        )
        if args.json:
            _print_json({"evaluations": rows})
            return
        if not rows:
            print(f"No evaluations in last {args.hours}h")
            return
        print(f"Recent evaluations ({len(rows)} rows, last {args.hours}h)")
        for row in rows:
            ts = datetime.fromtimestamp(row["timestamp"], UTC).isoformat(
                timespec="seconds"
            )
            fired_marker = "FIRED" if row["fired"] else "  -  "
            print(
                f"  {ts}  {row['ticker']:<6}  {fired_marker}  "
                f"cycle={row['cycle_id']}  candidate={row['candidate_id']}"
            )
            if row["full_analysis_summary"]:
                print(f"    {row['full_analysis_summary']}")
    finally:
        conn.close()


async def _cmd_candidates(_client: MarketDataClient, args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        rows = fetch_recent_candidates(conn, status=args.status)
        if args.json:
            _print_json({"candidates": rows})
            return
        if not rows:
            print("No candidates")
            return
        print(f"Candidates ({len(rows)})")
        for row in rows:
            ts = datetime.fromtimestamp(row["created_ts"], UTC).isoformat(
                timespec="seconds"
            )
            print(
                f"  #{row['id']:<4} {ts}  {row['ticker']:<6}  {row['direction']:<10}  "
                f"{row['candidate_kind']:<6}  status={row['status']}  strat={row['strategy_name']}"
            )
    finally:
        conn.close()


async def _cmd_candidate(_client: MarketDataClient, args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        row = fetch_candidate(conn, args.candidate_id)
        if row is None:
            raise SystemExit(f"Candidate #{args.candidate_id} not found")
        if args.json:
            _print_json(row)
            return
        print(
            f"Candidate #{row['id']}  {row['ticker']}  {row['direction']}  "
            f"status={row['status']}"
        )
        print(f"  Strategy: {row['strategy_name']}  kind: {row['candidate_kind']}")
        if row["rule_trace_json"]:
            trace = RuleTrace.model_validate_json(row["rule_trace_json"])
            _print_rule_trace(trace)
        if row["overrides_applied_json"]:
            overrides = json.loads(row["overrides_applied_json"])
            if overrides:
                print(f"  Overrides applied: {overrides}")
        if row["shortlist_json"]:
            shortlist = json.loads(row["shortlist_json"])
            print(f"  Shortlist ({len(shortlist)} contracts):")
            for c in shortlist:
                print(
                    f"    {c['symbol']}  dte={c['dte']}  strike={c['strike']}  "
                    f"delta={c['delta']}  oi={c['open_interest']}  vol={c['volume']}"
                )
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="services.scanner.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan-now", help="Run one scan cycle now")
    p_scan.add_argument("--json", action="store_true")

    p_st = sub.add_parser("scan-ticker", help="Evaluate one ticker manually")
    p_st.add_argument("ticker")
    p_st.add_argument("--json", action="store_true")

    p_ev = sub.add_parser("evaluations", help="Recent scan evaluations")
    p_ev.add_argument("--ticker", default=None)
    p_ev.add_argument("--hours", type=int, default=24)
    p_ev.add_argument("--json", action="store_true")

    p_cs = sub.add_parser("candidates", help="Recent fired candidates")
    p_cs.add_argument("--status", default=None)
    p_cs.add_argument("--json", action="store_true")

    p_c = sub.add_parser("candidate", help="Detail of one candidate")
    p_c.add_argument("candidate_id", type=int)
    p_c.add_argument("--json", action="store_true")

    return parser


_HANDLERS = {
    "scan-now": _cmd_scan_now,
    "scan-ticker": _cmd_scan_ticker,
    "evaluations": _cmd_evaluations,
    "candidates": _cmd_candidates,
    "candidate": _cmd_candidate,
}


async def _run(args: argparse.Namespace) -> None:
    run_migrations()
    client = make_market_data_client(settings)
    if isinstance(client, MockDataClient):
        client.seed_iv_history()
    await _HANDLERS[args.cmd](client, args)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
