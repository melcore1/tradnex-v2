"""TradNex evaluator CLI.

Examples:
    python -m services.evaluator.cli evaluate 1
    python -m services.evaluator.cli queue
    python -m services.evaluator.cli evaluations --hours 24
    python -m services.evaluator.cli prompt show entry_evaluation
    python -m services.evaluator.cli prompt history entry_evaluation
    python -m services.evaluator.cli prompt activate 5
    python -m services.evaluator.cli prompt rollback entry_evaluation 1
    python -m services.evaluator.cli health
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from services.evaluator.evaluate import evaluate_candidate
from services.evaluator.persistence import (
    claim_candidate_for_llm_eval,
    fetch_pending_llm_candidate_ids,
    fetch_recent_evaluations,
)
from shared.clients.factory import make_claude_client, make_exa_client
from shared.config import settings
from shared.db import get_connection, run_migrations
from shared.services.prompts import (
    activate_prompt_version,
    get_active_prompt,
    get_prompt_history,
    rollback_to_version,
)
from shared.strategy.settings import StrategySettings


def _print_json(obj: Any) -> None:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    print(json.dumps(obj, indent=2, default=str))


async def _cmd_evaluate(args: argparse.Namespace) -> None:
    cfg = StrategySettings().evaluator
    claude = make_claude_client(settings)
    exa = make_exa_client(settings)
    claim_conn = get_connection()
    try:
        claimed = await claim_candidate_for_llm_eval(claim_conn, args.candidate_id)
    finally:
        claim_conn.close()
    if not claimed:
        # Status not in pending_llm_evaluation. Check the row state.
        check = get_connection()
        try:
            row = check.execute(
                "SELECT status FROM candidates WHERE id = ?",
                (args.candidate_id,),
            ).fetchone()
        finally:
            check.close()
        if row is None:
            raise SystemExit(f"Candidate #{args.candidate_id} not found")
        raise SystemExit(
            f"Candidate #{args.candidate_id} status='{row['status']}' — "
            f"only pending_llm_evaluation can be claimed"
        )
    worker = get_connection()
    try:
        result = await evaluate_candidate(
            args.candidate_id, worker, claude, exa, cfg
        )
    finally:
        worker.close()
    if args.json:
        _print_json(result)
        return
    print(f"Candidate #{args.candidate_id}")
    print(f"  decision:    {result.decision}")
    print(f"  confidence:  {result.confidence}")
    print(f"  new_status:  {result.new_status}")
    print(f"  fallback:    {result.fallback}")
    if result.fallback_reason:
        print(f"  reason:      {result.fallback_reason}")
    print(f"  eval_id:     {result.eval_id}")


async def _cmd_queue(args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        pending = fetch_pending_llm_candidate_ids(conn)
        processing_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM candidates "
                "WHERE status = 'processing_llm_evaluation'"
            ).fetchone()[0]
        )
    finally:
        conn.close()
    if args.json:
        _print_json(
            {
                "pending_candidate_ids": pending,
                "processing_count": processing_count,
            }
        )
        return
    print(f"Pending: {len(pending)} candidate(s) — {pending}")
    print(f"Processing (in-flight): {processing_count}")


async def _cmd_evaluations(args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        rows = fetch_recent_evaluations(
            conn, candidate_id=args.candidate, hours=args.hours
        )
    finally:
        conn.close()
    if args.json:
        _print_json({"evaluations": rows})
        return
    if not rows:
        print(f"No evaluations in the last {args.hours} hours")
        return
    print(f"{len(rows)} recent evaluation(s):")
    for r in rows:
        marker = "FALLBACK" if r["fallback_used"] else "claude"
        print(
            f"  #{r['id']}  cand={r['candidate_id']}  {r['prompt_template_name']}  "
            f"{marker:>8}  decision={r['decision']:<14}  "
            f"elapsed={r['elapsed_ms']}ms"
        )
        if r["fallback_used"] and r["fallback_reason"]:
            print(f"      reason: {r['fallback_reason']}")


async def _cmd_prompt_show(args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        version = await get_active_prompt(conn, args.template_name)
    finally:
        conn.close()
    if args.json:
        _print_json(version)
        return
    print(f"Active prompt for '{args.template_name}':")
    print(f"  version: v{version.version_number}  id={version.id}")
    print(f"  status:  {version.status}")
    print(f"  by:      {version.created_by}")
    print(f"  created: {version.created_ts.isoformat()}")
    if version.notes:
        print(f"  notes:   {version.notes}")
    print()
    print(version.template_text)


async def _cmd_prompt_history(args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        history = await get_prompt_history(conn, args.template_name)
    finally:
        conn.close()
    if args.json:
        _print_json([v.model_dump(mode="json") for v in history])
        return
    print(f"History for '{args.template_name}' ({len(history)} version(s)):")
    for v in history:
        marker = (
            "*"
            if v.status == "active"
            else " " if v.status == "deprecated" else "p"
        )
        print(
            f"  {marker} v{v.version_number}  id={v.id}  status={v.status:<10}  "
            f"by={v.created_by}"
        )
        if v.notes:
            print(f"      notes: {v.notes}")


async def _cmd_prompt_activate(args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        version = await activate_prompt_version(conn, args.version_id)
    finally:
        conn.close()
    if args.json:
        _print_json(version)
        return
    print(
        f"Activated v{version.version_number} (id={version.id}) for "
        f"template '{version.template_name}'"
    )


async def _cmd_prompt_rollback(args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        version = await rollback_to_version(
            conn, args.template_name, args.version_number
        )
    finally:
        conn.close()
    if args.json:
        _print_json(version)
        return
    print(
        f"Rolled back to v{version.version_number} (id={version.id}) for "
        f"template '{version.template_name}'"
    )


async def _cmd_health(args: argparse.Namespace) -> None:
    claude = make_claude_client(settings)
    exa = make_exa_client(settings)
    claude_ok = await claude.health_check()
    exa_ok = await exa.health_check()
    if args.json:
        _print_json(
            {
                "claude_client": settings.CLAUDE_CLIENT,
                "claude_ok": claude_ok,
                "exa_ok": exa_ok,
            }
        )
        return
    print(f"Claude client: {settings.CLAUDE_CLIENT}  ok={claude_ok}")
    print(f"Exa client:    ok={exa_ok}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="services.evaluator.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_e = sub.add_parser("evaluate", help="Evaluate one candidate now")
    p_e.add_argument("candidate_id", type=int)
    p_e.add_argument("--json", action="store_true")

    p_q = sub.add_parser("queue", help="Show queue state (pending + in-flight)")
    p_q.add_argument("--json", action="store_true")

    p_ev = sub.add_parser("evaluations", help="List recent llm_evaluations rows")
    p_ev.add_argument("--hours", type=int, default=24)
    p_ev.add_argument("--candidate", type=int, default=None)
    p_ev.add_argument("--json", action="store_true")

    pp = sub.add_parser("prompt", help="Prompt-version commands")
    pps = pp.add_subparsers(dest="prompt_cmd", required=True)

    pps_show = pps.add_parser("show", help="Show the active prompt for a template")
    pps_show.add_argument(
        "template_name", choices=("entry_evaluation", "exit_evaluation")
    )
    pps_show.add_argument("--json", action="store_true")

    pps_hist = pps.add_parser("history", help="Show all versions of a template")
    pps_hist.add_argument(
        "template_name", choices=("entry_evaluation", "exit_evaluation")
    )
    pps_hist.add_argument("--json", action="store_true")

    pps_act = pps.add_parser("activate", help="Activate a pending version by id")
    pps_act.add_argument("version_id", type=int)
    pps_act.add_argument("--json", action="store_true")

    pps_rb = pps.add_parser(
        "rollback", help="Activate a previous version by template + version_number"
    )
    pps_rb.add_argument(
        "template_name", choices=("entry_evaluation", "exit_evaluation")
    )
    pps_rb.add_argument("version_number", type=int)
    pps_rb.add_argument("--json", action="store_true")

    p_h = sub.add_parser("health", help="Probe Claude + Exa client health")
    p_h.add_argument("--json", action="store_true")

    return parser


_HANDLERS = {
    "evaluate": _cmd_evaluate,
    "queue": _cmd_queue,
    "evaluations": _cmd_evaluations,
    "health": _cmd_health,
}

_PROMPT_HANDLERS = {
    "show": _cmd_prompt_show,
    "history": _cmd_prompt_history,
    "activate": _cmd_prompt_activate,
    "rollback": _cmd_prompt_rollback,
}


async def _run(args: argparse.Namespace) -> None:
    run_migrations()
    if args.cmd == "prompt":
        await _PROMPT_HANDLERS[args.prompt_cmd](args)
        return
    await _HANDLERS[args.cmd](args)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
