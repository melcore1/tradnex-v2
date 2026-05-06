"""Prompt rendering: combine candidate context + Exa news + active prompt
template into a single prompt string for Claude.

Phase 5 design:
  - Pre-fetch Exa articles (top 3, last 7 days) inline
  - Pre-fetch upcoming calendar events (14 days)
  - Truncate shortlist to 5 contracts (entry only)
  - Simple `str.format_map` substitution; missing keys raise KeyError
  - Hard token-budget guardrail before returning — caller falls back if
    rendered prompt exceeds the budget
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel

from shared.clients.exa_news import ExaArticle, ExaClient
from shared.services.calendar_service import CalendarService
from shared.services.prompts import PromptVersion, get_active_prompt
from shared.strategy.base import EntryCandidate, ExitCandidate
from shared.strategy.settings import EvaluatorSettings


class PromptTooLargeError(Exception):
    def __init__(self, rendered_len: int, budget_chars: int) -> None:
        super().__init__(
            f"rendered prompt is {rendered_len} chars, "
            f"exceeds budget {budget_chars}"
        )
        self.rendered_len = rendered_len
        self.budget_chars = budget_chars


def _to_json(obj: Any) -> str:
    """JSON-stringify Pydantic models, lists thereof, or plain values."""
    if obj is None:
        return "null"
    if isinstance(obj, BaseModel):
        return obj.model_dump_json()
    if isinstance(obj, list):
        return json.dumps(
            [
                o.model_dump(mode="json") if isinstance(o, BaseModel) else o
                for o in obj
            ],
            default=str,
        )
    if isinstance(obj, dict):
        return json.dumps(obj, default=str)
    return json.dumps(obj, default=str)


async def _calendar_context(
    conn: sqlite3.Connection,
    ticker: str | None,
    *,
    days: int = 14,
) -> str:
    """Render upcoming events as a compact JSON list."""
    svc = CalendarService(conn)
    now = datetime.now(UTC)
    end = now + timedelta(days=days)
    economic = await svc.get_events_in_window(
        now, end, event_type="economic"
    )
    earnings: list[Any] = []
    if ticker:
        earnings = await svc.get_events_in_window(
            now, end, event_type="earnings", ticker=ticker
        )
    rows = [
        {
            "type": e.event_type,
            "name": e.event_name,
            "ticker": e.ticker,
            "when_utc": e.event_datetime_utc.isoformat(),
            "impact": e.impact,
        }
        for e in (economic + earnings)
    ]
    return json.dumps(rows, default=str)


def _articles_to_json(articles: list[ExaArticle]) -> str:
    return json.dumps(
        [
            {
                "title": a.title,
                "url": a.url,
                "published_date": (
                    a.published_date.isoformat() if a.published_date else None
                ),
                "summary": a.summary,
            }
            for a in articles
        ],
        default=str,
    )


def _check_budget(rendered: str, cfg: EvaluatorSettings) -> None:
    budget_chars = cfg.prompt_token_budget * 4  # rough char/4 budget
    if len(rendered) > budget_chars:
        raise PromptTooLargeError(len(rendered), budget_chars)


async def build_entry_prompt(
    candidate: EntryCandidate,
    conn: sqlite3.Connection,
    exa_client: ExaClient,
    cfg: EvaluatorSettings,
) -> tuple[str, PromptVersion, list[ExaArticle]]:
    """Render the active entry-evaluation template with candidate data.

    Returns (rendered_prompt, version_used, articles_fetched).
    """
    version = await get_active_prompt(conn, "entry_evaluation")
    articles = await exa_client.fetch_news(
        candidate.ticker,
        lookback_days=cfg.exa_news_lookback_days,
        max_results=cfg.exa_news_max_articles,
    )

    shortlist_5 = (candidate.shortlist or [])[:5]

    subs: dict[str, str] = {
        "ticker": candidate.ticker,
        "direction": candidate.direction,
        "confidence": candidate.confidence,
        "rule_trace": _to_json(candidate.rule_trace),
        "full_analysis": _to_json(candidate.full_analysis),
        "options_analysis": _to_json(candidate.options_analysis),
        "regime": _to_json(candidate.regime),
        "shortlist": _to_json(shortlist_5),
        "calendar_context": await _calendar_context(conn, candidate.ticker, days=14),
        "exa_articles": _articles_to_json(articles),
    }
    rendered = version.template_text.format_map(subs)
    _check_budget(rendered, cfg)
    return rendered, version, articles


def _fetch_position_context(
    conn: sqlite3.Connection,
    position_id: int,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts FROM positions WHERE id = ?",
        (position_id,),
    ).fetchone()
    if row is None:
        return {
            "contract_symbol": "(unknown)",
            "side": "(unknown)",
            "quantity": 0,
            "entry_price": "0",
            "entry_ts": "",
        }
    return {
        "contract_symbol": row["contract_symbol"],
        "side": row["side"],
        "quantity": int(row["quantity"]),
        "entry_price": str(row["entry_price"]),
        "entry_ts": datetime.fromtimestamp(
            float(row["entry_ts"]), tz=UTC
        ).isoformat(),
    }


async def build_exit_prompt(
    candidate: ExitCandidate,
    conn: sqlite3.Connection,
    exa_client: ExaClient,
    cfg: EvaluatorSettings,
) -> tuple[str, PromptVersion, list[ExaArticle]]:
    """Render the active exit-evaluation template with candidate data."""
    version = await get_active_prompt(conn, "exit_evaluation")
    articles = await exa_client.fetch_news(
        candidate.ticker,
        lookback_days=cfg.exa_news_lookback_days,
        max_results=cfg.exa_news_max_articles,
    )
    pos_ctx = _fetch_position_context(conn, candidate.position_id)

    subs: dict[str, str] = {
        "ticker": candidate.ticker,
        "position_id": str(candidate.position_id),
        "contract_symbol": str(pos_ctx["contract_symbol"]),
        "side": str(pos_ctx["side"]),
        "quantity": str(pos_ctx["quantity"]),
        "entry_price": str(pos_ctx["entry_price"]),
        "entry_ts": str(pos_ctx["entry_ts"]),
        "pnl_pct": str(candidate.pnl_pct),
        "pnl_dollars": str(candidate.pnl_dollars),
        "dte_remaining": str(candidate.dte_remaining),
        "signal_trace": _to_json(candidate.signal_trace),
        "triggered_signals": json.dumps(candidate.triggered_signals),
        "regime": "{}",  # exits don't carry regime in candidate; placeholder
        "calendar_context": await _calendar_context(conn, candidate.ticker, days=14),
        "exa_articles": _articles_to_json(articles),
    }
    rendered = version.template_text.format_map(subs)
    _check_budget(rendered, cfg)
    return rendered, version, articles
