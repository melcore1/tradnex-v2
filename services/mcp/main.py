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
from starlette.responses import JSONResponse, RedirectResponse, Response

from services.mcp.auth import MCPApiKeyVerifier, load_stored_api_key
from services.mcp.deps import build_data_client
from services.mcp.oauth_token import (
    OAuthTokenError,
    build_metadata,
    consume_auth_code,
    issue_auth_code,
    issue_jwt,
)
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


@mcp.custom_route(  # type: ignore[untyped-decorator]
    "/.well-known/oauth-authorization-server", methods=["GET"]
)
async def oauth_metadata(_: Request) -> JSONResponse:
    """RFC 8414 authorization-server metadata.

    Claude.ai's Custom Connector beta discovers our token endpoint here when
    OAuth Client ID/Secret are configured. We declare only the
    ``client_credentials`` grant since this is a single-user shared-secret
    deployment.
    """
    return JSONResponse(build_metadata(str(_RESOURCE_URL)))


_ALLOWED_REDIRECT_PREFIXES = (
    "https://claude.ai/",
    "https://claude.com/",
    "http://localhost",
    "http://127.0.0.1",
)


@mcp.custom_route("/authorize", methods=["GET"])  # type: ignore[untyped-decorator]
async def oauth_authorize(request: Request) -> Response:
    """OAuth 2.1 authorization endpoint (RFC 6749 §4.1) with PKCE (RFC 7636).

    Auto-approves the request — there's no separate consent UI because this
    is a single-user deployment gated by the API key on the /token exchange.
    Generates an auth code, stores the PKCE challenge keyed by it, and
    302-redirects to ``redirect_uri`` with ``code`` + ``state``.
    """
    params = request.query_params
    response_type = params.get("response_type", "")
    client_id = params.get("client_id", "") or "claude-ai"
    redirect_uri = params.get("redirect_uri", "")
    code_challenge = params.get("code_challenge", "")
    code_challenge_method = params.get("code_challenge_method", "")
    state = params.get("state", "")
    scope = params.get("scope", "analytics:read")

    if not redirect_uri:
        return JSONResponse(
            {"error": "invalid_request", "error_description": "redirect_uri required"},
            status_code=400,
        )
    if not redirect_uri.startswith(_ALLOWED_REDIRECT_PREFIXES):
        return JSONResponse(
            {
                "error": "invalid_request",
                "error_description": (
                    "redirect_uri must be https://claude.ai/, https://claude.com/, "
                    "or a localhost URL."
                ),
            },
            status_code=400,
        )
    if response_type != "code":
        return _redirect_oauth_error(
            redirect_uri,
            "unsupported_response_type",
            "Only `code` is supported.",
            state,
        )
    if not code_challenge:
        return _redirect_oauth_error(
            redirect_uri, "invalid_request", "code_challenge required (PKCE).", state
        )
    if code_challenge_method != "S256":
        return _redirect_oauth_error(
            redirect_uri,
            "invalid_request",
            "Only S256 code_challenge_method is supported.",
            state,
        )

    code = issue_auth_code(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        scope=scope,
    )
    target = f"{redirect_uri}?code={code}"
    if state:
        target += f"&state={state}"
    logger.info("issued auth code for client_id=%s", client_id)
    return RedirectResponse(target, status_code=302)


@mcp.custom_route("/oauth/token", methods=["POST"])  # type: ignore[untyped-decorator]
async def oauth_token(request: Request) -> JSONResponse:
    """OAuth 2.1 token endpoint. Handles two grant types:

    1. ``authorization_code`` + ``code`` + ``code_verifier`` (Claude.ai's flow).
       PKCE is required. ``client_secret`` is an additional check; we accept
       requests with no client_secret only if PKCE has already authenticated
       the caller (per RFC 7636 §4.4 the verifier is auth).
    2. ``client_credentials`` + ``client_secret`` (direct curl/CLI).

    Issued tokens are HS256 JWTs signed with the stored ``mcp_api_key``.
    """
    try:
        stored_key = load_stored_api_key()
        if stored_key is None:
            raise OAuthTokenError(
                "server_error",
                "MCP API key is not configured. Run `python -m services.mcp.cli "
                "generate-api-key` inside the container before connecting.",
                status_code=500,
            )

        form = await request.form()
        grant_type = str(form.get("grant_type", "")).strip()

        if grant_type == "authorization_code":
            client_id = _form_str(form, "client_id") or "claude-ai"
            code = _form_str(form, "code")
            code_verifier = _form_str(form, "code_verifier")
            if not code or not code_verifier:
                raise OAuthTokenError(
                    "invalid_request",
                    "code and code_verifier are required for authorization_code grant.",
                )
            data = consume_auth_code(code, code_verifier)
            if data is None:
                raise OAuthTokenError(
                    "invalid_grant",
                    "Auth code is invalid, expired, already used, or PKCE check failed.",
                    status_code=400,
                )
            # Optional client_secret check: when Claude.ai's UI has the Client
            # Secret filled in, it sends it here. We require it to match the
            # api_key if present — defense in depth against a stolen code+verifier.
            sent_secret = _form_str(form, "client_secret")
            if sent_secret and not _constant_time_eq(sent_secret, stored_key):
                raise OAuthTokenError(
                    "invalid_client",
                    "client_secret does not match the configured mcp_api_key.",
                    status_code=401,
                )
            body = issue_jwt(
                stored_key,
                client_id=client_id,
                scopes=data.get("scope", "analytics:read").split(),
            )
            logger.info("issued jwt via authorization_code for client_id=%s", client_id)
            return JSONResponse(body)

        if grant_type == "client_credentials":
            client_id, client_secret = await _extract_client_credentials(request, form)
            if not _constant_time_eq(client_secret, stored_key):
                raise OAuthTokenError(
                    "invalid_client",
                    "client_secret does not match the configured mcp_api_key.",
                    status_code=401,
                )
            body = issue_jwt(stored_key, client_id=client_id)
            logger.info("issued jwt via client_credentials for client_id=%s", client_id)
            return JSONResponse(body)

        raise OAuthTokenError(
            "unsupported_grant_type",
            f"grant_type must be `authorization_code` or `client_credentials` "
            f"(got {grant_type!r}).",
            status_code=400,
        )
    except OAuthTokenError as exc:
        logger.warning("oauth grant rejected: %s — %s", exc.error, exc.description)
        return JSONResponse(
            {"error": exc.error, "error_description": exc.description},
            status_code=exc.status_code,
        )
    except Exception:
        logger.exception("unexpected error in /oauth/token")
        return JSONResponse(
            {"error": "server_error", "error_description": "Internal error."},
            status_code=500,
        )


def _redirect_oauth_error(
    redirect_uri: str, error: str, description: str, state: str
) -> RedirectResponse:
    """Build a 302 back to the OAuth client with an error payload (RFC 6749 §4.1.2.1)."""
    from urllib.parse import urlencode

    qs = {"error": error, "error_description": description}
    if state:
        qs["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(qs)}", status_code=302)


def _form_str(form: Any, key: str) -> str:
    val = form.get(key, "")
    return str(val).strip() if val is not None else ""


async def _extract_client_credentials(
    request: Request, form: Any
) -> tuple[str, str]:
    """Extract (client_id, client_secret) for client_credentials grant."""
    body_id = _form_str(form, "client_id") or "claude-ai"
    body_secret = _form_str(form, "client_secret")
    if body_secret:
        return body_id, body_secret

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        import base64

        try:
            decoded = base64.b64decode(auth_header[6:]).decode()
            client_id, _, client_secret = decoded.partition(":")
        except Exception as exc:
            raise OAuthTokenError(
                "invalid_request", "Malformed Basic credentials.", status_code=400
            ) from exc
        if not client_secret:
            raise OAuthTokenError(
                "invalid_request", "Basic auth missing client_secret.", status_code=400
            )
        return client_id.strip() or "claude-ai", client_secret

    raise OAuthTokenError(
        "invalid_request",
        "Missing client_secret for client_credentials grant.",
        status_code=400,
    )


def _constant_time_eq(a: str, b: str) -> bool:
    import hmac as _hmac

    return _hmac.compare_digest(a, b)


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
