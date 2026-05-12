"""TradNex 2 MCP server entry point.

Wraps `shared/analytics/` as a remote MCP server reachable from Claude.ai at
`https://scoutv2.meltradingmcp.uk/mcp` (and `/sse` for the legacy transport
during the current Claude.ai connector regression).

Run with: `python -m services.mcp.main` or via uvicorn directly:
    uvicorn services.mcp.main:app --host 0.0.0.0 --port 8090

Tool dispatch is *not* a plain function call — the SDK runs each tool as its
own async task on the event loop and serializes results via the MCP
JSON-RPC protocol. Tools must be coroutines.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from services.mcp.auth import MCPApiKeyVerifier
from services.mcp.deps import build_data_client
from services.mcp.tools.calendar_check import calendar_check as _calendar_check
from services.mcp.tools.correlation_check import (
    correlation_check as _correlation_check,
)
from services.mcp.tools.market_overview import (
    market_overview as _market_overview,
)
from services.mcp.tools.position_check import position_check as _position_check
from services.mcp.tools.quick_check import quick_check as _quick_check
from services.mcp.tools.regime_check import regime_check as _regime_check
from services.mcp.tools.scout import scout as _scout

logger = logging.getLogger(__name__)

# Resource server URL is used in the SDK's RFC 9728 protected-resource
# metadata response (`/.well-known/oauth-protected-resource`). For a
# private LAN deployment with shared-secret bearer auth, the URL just
# needs to be a valid HTTP(S) URL; clients don't follow it.
_RESOURCE_URL = AnyHttpUrl("https://scoutv2.meltradingmcp.uk")
_ISSUER_URL = AnyHttpUrl("https://scoutv2.meltradingmcp.uk")


mcp = FastMCP(
    name="TradNex 2 MCP",
    instructions=(
        "TradNex 2 analytics — Schwab-backed quantitative tools.\n\n"
        "IMPORTANT: When asking about multiple tickers, pass ALL tickers in a "
        "single call as a list (e.g., quick_check(['SPY', 'NVDA'])). Tools run "
        "in parallel. Maximum 10 tickers per call. One bad ticker (halted, "
        "delisted, unknown) returns an `error` field for that key without "
        "affecting the others."
    ),
    json_response=True,
    stateless_http=True,
    token_verifier=MCPApiKeyVerifier(),
    auth=AuthSettings(
        issuer_url=_ISSUER_URL,
        resource_server_url=_RESOURCE_URL,
        required_scopes=["analytics:read"],
    ),
)


@mcp.tool()
async def quick_check(ticker: str | list[str]) -> dict[str, Any]:
    """Lightweight per-ticker snapshot: price, RSI, volume, levels, ATR.

    For position monitoring throughout the trading day. Returns a flat dict
    for one ticker, or a dict-of-dicts for a list. Maximum 10 tickers per call.
    """
    client = build_data_client()
    return await _quick_check(ticker, client)


@mcp.tool()
async def scout(
    ticker: str | list[str], days_history: int = 60
) -> dict[str, Any]:
    """Full quant analysis — Tier 2 trend/volatility/momentum + Tier 3 options + regime.

    Use for fresh ideas or pre-entry due diligence. Slower than quick_check.
    Maximum 10 tickers per call. `days_history` is 30–500.
    """
    client = build_data_client()
    return await _scout(ticker, days_history, client)


@mcp.tool()
async def market_overview(
    market_type: Literal["stocks", "crypto"] = "stocks",
) -> dict[str, Any]:
    """Top gainers / losers / most-active for the day.

    Crypto mode returns an informational note — TradNex 2 is equities/options only.
    """
    client = build_data_client()
    return await _market_overview(market_type, client)


@mcp.tool()
async def regime_check(ticker: str) -> dict[str, Any]:
    """Categorical market-regime classification for one ticker.

    Combines trend + volatility + gamma + IV signals into a single label.
    """
    client = build_data_client()
    return await _regime_check(ticker, client)


@mcp.tool()
async def correlation_check(ticker_a: str, ticker_b: str) -> dict[str, Any]:
    """Pairwise correlation from the cached overnight correlation matrix.

    Returns a friendly note when the pair isn't in the cache (e.g. one ticker
    not in the static universe).
    """
    return await _correlation_check(ticker_a, ticker_b)


@mcp.tool()
async def position_check() -> dict[str, Any]:
    """List current open positions with their latest monitor evaluation.

    Sensitive data — gated by the Bearer-token middleware. Returns an empty
    list when there are no open positions.
    """
    return await _position_check()


@mcp.tool()
async def calendar_check(
    days_ahead: int = 14, ticker: str | None = None
) -> dict[str, Any]:
    """Upcoming economic/earnings events from the calendar cache.

    Window is 1–90 days ahead. Optional ticker filter narrows to that
    symbol's earnings/dividends only.
    """
    return await _calendar_check(days_ahead, ticker)


@mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]
async def health(_: Request) -> JSONResponse:
    """Unauthenticated health probe for Docker / Caddy / Cloudflare."""
    return JSONResponse({"status": "ok", "server": "tradnex-mcp"})


def build_app() -> Starlette:
    """Construct the FastMCP Streamable HTTP Starlette app.

    The SDK's `streamable_http_app()` already attaches the session manager
    lifespan and our `/health` custom route. Claude.ai connector default
    transport is Streamable HTTP; the endpoint Claude.ai connects to is
    `https://<host>/mcp` (streamable_http_path).
    """
    return mcp.streamable_http_app()


app = build_app()


def main() -> None:
    """CLI entry point: `python -m services.mcp.main`."""
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "services.mcp.main:app",
        host="0.0.0.0",  # noqa: S104 — server binds inside Docker network only
        port=8090,
        log_level="info",
    )


if __name__ == "__main__":
    main()
