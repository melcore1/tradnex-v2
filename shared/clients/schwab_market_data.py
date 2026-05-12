"""Schwab Trader API implementation of MarketDataClient.

Wraps schwab-py's AsyncClient. The module imports without requiring credentials;
construction validates credentials and loads a persisted OAuth token. Tests
inject a pre-built AsyncClient via the `_client` kwarg to bypass real auth.
"""

from __future__ import annotations

import asyncio
import time as _time
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from shared.clients.market_data import (
    ContractTypeFilter,
    MarketDataClient,
    Timeframe,
)
from shared.schemas.market import (
    AccountState,
    Bar,
    ContractType,
    MarketStatus,
    MoverEntry,
    Movers,
    OptionContract,
    OptionsChain,
    Quote,
)

if TYPE_CHECKING:
    from schwab.client import AsyncClient


class SchwabAuthRequired(Exception):
    """Token missing or refresh failed beyond automatic recovery."""


class SchwabRateLimited(Exception):
    """Schwab returned 429 Too Many Requests."""


class SchwabApiError(Exception):
    """Schwab returned 5xx or another unexpected error."""


# Schwab's price-history API requires *compatible* period_type + frequency_type.
# Invalid combinations (e.g. period_type=day + frequency_type=daily) return 400.
# Reference: https://developer.schwab.com/products/trader-api--individual/details/specifications/Retail%20Trader%20API%20Production
#   period_type=day  → frequency_type=minute  (period: 1-5, 10)
#   period_type=year → frequency_type=daily|weekly|monthly (period: 1-3, 5, 10, 15, 20)
_TIMEFRAME_TO_SCHWAB: dict[str, dict[str, Any]] = {
    "1m":  {"period_type": "day",  "period": 10, "frequency_type": "minute", "frequency": 1},
    "5m":  {"period_type": "day",  "period": 10, "frequency_type": "minute", "frequency": 5},
    "15m": {"period_type": "day",  "period": 10, "frequency_type": "minute", "frequency": 15},
    "1h":  {"period_type": "day",  "period": 10, "frequency_type": "minute", "frequency": 30},
    "1d":  {"period_type": "year", "period": 1,  "frequency_type": "daily",  "frequency": 1},
}


def _is_us_market_hours_now() -> bool:
    """Cheap heuristic: M-F 13:30-20:00 UTC. Doesn't handle holidays or DST shifts."""
    now = datetime.now(UTC)
    if now.weekday() >= 5:
        return False
    return time(13, 30) <= now.time() <= time(20, 0)


def _decimal(value: float | int | str | None, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


class SchwabDataClient(MarketDataClient):
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        token_path: str | None = None,
        *,
        tokens_provider: Callable[[], dict[str, Any]] | None = None,
        tokens_writer: Callable[[dict[str, Any]], None] | None = None,
        _client: AsyncClient | None = None,
    ) -> None:
        if _client is not None:
            self._client = _client
            return

        if tokens_provider is not None:
            # Phase 8a.5 path: tokens come from the encrypted credentials
            # store via a caller-supplied closure. `tokens_writer` (optional)
            # is invoked when schwab-py auto-refreshes; default is no-op
            # because the 25-min background task owns refresh.
            if not client_id or not client_secret:
                raise SchwabAuthRequired(
                    "Schwab credentials required: client_id, client_secret"
                )
            try:
                from schwab.auth import client_from_access_functions
            except ImportError as e:  # pragma: no cover
                raise SchwabAuthRequired(f"schwab-py not installed: {e}") from e

            def _read() -> dict[str, Any]:
                inner = tokens_provider()
                if not inner:
                    raise SchwabAuthRequired(
                        "Schwab tokens missing from credentials store"
                    )
                return {"token": inner, "creation_timestamp": _time.time()}

            def _write(token: dict[str, Any], *args: Any, **kwargs: Any) -> None:
                if tokens_writer is not None:
                    tokens_writer(token)

            try:
                self._client = client_from_access_functions(
                    api_key=client_id,
                    app_secret=client_secret,
                    token_read_func=_read,
                    token_write_func=_write,
                    asyncio=True,
                    # We pass raw strings ("equity", sort orders, etc.)
                    # rather than Market.EQUITY enums into schwab-py.
                    # Without this flag, get_market_hours("equity") raises
                    # ValueError('expected type "Market", got type "str"').
                    enforce_enums=False,
                )
            except Exception as e:
                raise SchwabAuthRequired(
                    f"Failed to build Schwab client from tokens_provider: {e}"
                ) from e
            return

        if not all([client_id, client_secret, redirect_uri, token_path]):
            raise SchwabAuthRequired(
                "Schwab credentials required: client_id, client_secret, redirect_uri, token_path"
            )

        assert token_path is not None  # narrowed
        if not Path(token_path).exists():
            raise SchwabAuthRequired(
                f"Schwab token not found at {token_path}. "
                f"Run scripts/schwab_auth.py to perform initial OAuth flow."
            )

        try:
            from schwab.auth import client_from_token_file
        except ImportError as e:  # pragma: no cover
            raise SchwabAuthRequired(f"schwab-py not installed: {e}") from e

        try:
            self._client = client_from_token_file(
                token_path=token_path,
                api_key=client_id,
                app_secret=client_secret,
                asyncio=True,
            )
        except Exception as e:
            raise SchwabAuthRequired(f"Failed to load Schwab token: {e}") from e

    def _raise_for_status(self, response: httpx.Response) -> None:
        code = response.status_code
        if 200 <= code < 300:
            return
        if code == 401:
            raise SchwabAuthRequired(f"401 Unauthorized: {response.text[:200]}")
        if code == 429:
            raise SchwabRateLimited(f"429 Rate limited: {response.text[:200]}")
        raise SchwabApiError(f"{code}: {response.text[:200]}")

    def _map_quote(self, ticker: str, data: dict[str, Any]) -> Quote:
        ticker_data = data.get(ticker) or data.get(ticker.upper()) or {}
        quote = ticker_data.get("quote", {})
        fundamental = ticker_data.get("fundamental", {})
        last = quote.get("lastPrice", quote.get("mark", 0))
        return Quote(
            ticker=ticker.upper(),
            spot=_decimal(last),
            bid=_decimal(quote.get("bidPrice", last)),
            ask=_decimal(quote.get("askPrice", last)),
            bid_size=int(quote.get("bidSize", 0) or 0),
            ask_size=int(quote.get("askSize", 0) or 0),
            day_open=_decimal(quote.get("openPrice", last)),
            day_high=_decimal(quote.get("highPrice", last)),
            day_low=_decimal(quote.get("lowPrice", last)),
            prev_close=_decimal(quote.get("closePrice", last)),
            volume=int(quote.get("totalVolume", 0) or 0),
            avg_volume_30d=int(fundamental.get("avg30DaysVolume", 0) or 0),
            is_market_open=_is_us_market_hours_now(),
            timestamp=datetime.now(UTC),
        )

    async def get_quote(self, ticker: str) -> Quote:
        response = await self._client.get_quote(ticker)
        self._raise_for_status(response)
        return self._map_quote(ticker, response.json())

    async def get_quotes(self, tickers: list[str]) -> dict[str, Quote]:
        response = await self._client.get_quotes(tickers)
        self._raise_for_status(response)
        data = response.json()
        return {t.upper(): self._map_quote(t, data) for t in tickers}

    async def get_bars(
        self,
        ticker: str,
        timeframe: Timeframe,
        limit: int = 200,
        end: datetime | None = None,
    ) -> list[Bar]:
        params = _TIMEFRAME_TO_SCHWAB[timeframe]
        end_ts = end or datetime.now(UTC)
        response = await self._client.get_price_history(
            ticker,
            period_type=params["period_type"],
            period=params["period"],
            frequency_type=params["frequency_type"],
            frequency=params["frequency"],
            end_datetime=end_ts,
        )
        self._raise_for_status(response)
        data = response.json()
        candles = data.get("candles", [])[-limit:]
        bars: list[Bar] = []
        for c in candles:
            ts = datetime.fromtimestamp(c["datetime"] / 1000, tz=UTC)
            vwap = c.get("vwap")
            bars.append(
                Bar(
                    timestamp=ts,
                    open=_decimal(c["open"]),
                    high=_decimal(c["high"]),
                    low=_decimal(c["low"]),
                    close=_decimal(c["close"]),
                    volume=int(c.get("volume", 0) or 0),
                    vwap=_decimal(vwap) if vwap is not None and timeframe != "1d" else None,
                )
            )
        return bars

    def _map_option_contract(
        self,
        contract_data: dict[str, Any],
        underlying: str,
        underlying_spot: Decimal,
        contract_type: ContractType,
    ) -> OptionContract:
        # Schwab returns IV as a percentage (e.g. 32.0 means 32%); convert to decimal.
        raw_iv = contract_data.get("volatility") or 0.0
        iv_decimal = Decimal(str(raw_iv)) / Decimal("100")
        exp_ms = contract_data.get("expirationDate", 0)
        exp_date = datetime.fromtimestamp(exp_ms / 1000, tz=UTC).date()
        return OptionContract(
            symbol=contract_data["symbol"].strip(),
            underlying=underlying,
            underlying_spot=underlying_spot,
            expiration=exp_date,
            dte=int(contract_data.get("daysToExpiration", 0)),
            strike=_decimal(contract_data["strikePrice"]),
            contract_type=contract_type,
            bid=_decimal(contract_data.get("bid", 0)),
            ask=_decimal(contract_data.get("ask", 0)),
            last=_decimal(contract_data["last"]) if contract_data.get("last") is not None else None,
            volume=int(contract_data.get("totalVolume", 0) or 0),
            open_interest=int(contract_data.get("openInterest", 0) or 0),
            iv=iv_decimal,
            delta=_decimal(contract_data.get("delta", 0)),
            gamma=_decimal(contract_data.get("gamma", 0)),
            theta=_decimal(contract_data.get("theta", 0)),
            vega=_decimal(contract_data.get("vega", 0)),
            rho=_decimal(contract_data.get("rho", 0)),
        )

    async def get_options_chain(
        self,
        ticker: str,
        min_dte: int | None = None,
        max_dte: int | None = None,
        contract_type: ContractTypeFilter = "both",
    ) -> OptionsChain:
        kwargs: dict[str, Any] = {}
        if min_dte is not None:
            kwargs["from_date"] = (datetime.now(UTC).date() + timedelta(days=min_dte))
        if max_dte is not None:
            kwargs["to_date"] = (datetime.now(UTC).date() + timedelta(days=max_dte))
        response = await self._client.get_option_chain(ticker, **kwargs)
        self._raise_for_status(response)
        data = response.json()

        underlying = ticker.upper()
        # Schwab returns "underlying": null when underlying data isn't available
        # (e.g. mid-after-hours, certain low-volume names). `.get(key, {})`
        # only kicks the default in when the key is missing, NOT when the
        # value is None — so guard with `or {}`.
        underlying_block = data.get("underlying") or {}
        spot = _decimal(underlying_block.get("last", 0))

        contracts: list[OptionContract] = []
        if contract_type in ("call", "both"):
            for _, strikes in (data.get("callExpDateMap") or {}).items():
                for _, contract_list in (strikes or {}).items():
                    for c in contract_list or []:
                        contracts.append(
                            self._map_option_contract(c, underlying, spot, "call")
                        )
        if contract_type in ("put", "both"):
            for _, strikes in (data.get("putExpDateMap") or {}).items():
                for _, contract_list in (strikes or {}).items():
                    for c in contract_list or []:
                        contracts.append(
                            self._map_option_contract(c, underlying, spot, "put")
                        )

        if min_dte is not None:
            contracts = [c for c in contracts if c.dte >= min_dte]
        if max_dte is not None:
            contracts = [c for c in contracts if c.dte <= max_dte]

        return OptionsChain(
            underlying=underlying,
            spot_at_fetch=spot,
            contracts=contracts,
            timestamp=datetime.now(UTC),
        )

    async def get_account_state(self) -> AccountState:
        accounts_response = await self._client.get_account_numbers()
        self._raise_for_status(accounts_response)
        accounts = accounts_response.json()
        if not accounts:
            raise SchwabApiError("No Schwab accounts returned")
        first = accounts[0]
        account_hash = first["hashValue"]
        account_id = first["accountNumber"]

        detail_response = await self._client.get_account(account_hash)
        self._raise_for_status(detail_response)
        detail = detail_response.json()
        sec = detail.get("securitiesAccount", detail)
        balances = sec.get("currentBalances", {})
        is_margin = sec.get("type", "").upper() == "MARGIN"
        day_trades_remaining = int(sec.get("roundTrips", 0))
        return AccountState(
            account_id=account_id,
            buying_power=_decimal(balances.get("buyingPower", 0)),
            cash=_decimal(balances.get("cashBalance", balances.get("cashAvailableForTrading", 0))),
            equity=_decimal(balances.get("equity", balances.get("liquidationValue", 0))),
            pdt_count_remaining=max(3 - day_trades_remaining, 0),
            is_pdt=bool(sec.get("isDayTrader", False)),
            margin_buying_power=_decimal(balances.get("buyingPower")) if is_margin else None,
            positions_count=len(sec.get("positions", []) or []),
            timestamp=datetime.now(UTC),
        )

    async def get_movers(self) -> Movers:
        async def _movers_for(sort_order: str) -> list[dict[str, Any]]:
            response = await self._client.get_movers(
                "$SPX",
                sort_order=sort_order,
                frequency=10,
            )
            self._raise_for_status(response)
            screeners: list[dict[str, Any]] = response.json().get("screeners", [])
            return screeners

        active_raw, gainers_raw, losers_raw = await asyncio.gather(
            _movers_for("VOLUME"),
            _movers_for("PERCENT_CHANGE_UP"),
            _movers_for("PERCENT_CHANGE_DOWN"),
        )

        def _to_entries(rows: list[dict[str, Any]], category: str) -> list[MoverEntry]:
            return [
                MoverEntry(
                    ticker=r.get("symbol", "").upper(),
                    last=_decimal(r.get("lastPrice", 0)),
                    change_pct=_decimal(r.get("netPercentChange", 0)),
                    volume=int(r.get("totalVolume", 0) or 0),
                    category=category,  # type: ignore[arg-type]
                )
                for r in rows[:10]
            ]

        return Movers(
            most_active=_to_entries(active_raw, "most_active"),
            top_gainers=_to_entries(gainers_raw, "top_gainer"),
            top_losers=_to_entries(losers_raw, "top_loser"),
            timestamp=datetime.now(UTC),
        )

    async def get_market_status(self) -> MarketStatus:
        response = await self._client.get_market_hours(["equity"])
        self._raise_for_status(response)
        data = response.json()
        equity = data.get("equity", {})
        # equity may be keyed by product (e.g. "EQ"); take the first entry.
        first: dict[str, Any] = next(iter(equity.values()), {}) if equity else {}
        is_open = bool(first.get("isOpen", _is_us_market_hours_now()))
        sessions = first.get("sessionHours", {}) or {}
        regular = (sessions.get("regularMarket") or [{}])[0]
        next_open = self._parse_session_time(regular.get("start"))
        next_close = self._parse_session_time(regular.get("end"))
        now = datetime.now(UTC)
        return MarketStatus(
            is_open=is_open,
            is_pre_market=bool(sessions.get("preMarket")) and not is_open,
            is_post_market=bool(sessions.get("postMarket")) and not is_open,
            next_open=next_open or (now + timedelta(hours=1)),
            next_close=next_close or (now + timedelta(hours=8)),
            timestamp=now,
        )

    @staticmethod
    def _parse_session_time(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            return None

    async def health_check(self) -> bool:
        try:
            await self.get_market_status()
            return True
        except Exception as exc:
            # Phase 8a.5: emit the real exception so onboarding failures
            # (missing expires_at, bad client_id, expired refresh window,
            # etc.) are debuggable from the events stream instead of just
            # showing "health_check_failed".
            try:
                from shared.events import emit

                emit(
                    "schwab_data",
                    "error",
                    "health_check_exception",
                    {
                        "error": str(exc)[:300],
                        "error_type": type(exc).__name__,
                    },
                )
            except Exception:
                # Best-effort logging — never let a logging failure mask
                # the underlying health_check result.
                pass
            return False
