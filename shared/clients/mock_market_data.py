"""Deterministic mock market data client.

Generates plausible quotes, bars, options chains, account state, movers, and
market status from a seedable RNG plus Black-Scholes for Greeks. Same seed
across instances yields identical first responses, so tests can assert
specific values; consecutive calls drift via random walk so behavior over
time looks live-ish.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import numpy as np
from numpy.random import Generator
from scipy.stats import norm

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
    MoverCategory,
    MoverEntry,
    Movers,
    OptionContract,
    OptionsChain,
    Quote,
)

DEFAULT_BASELINES: dict[str, Decimal] = {
    "NVDA": Decimal("142.50"),
    "AMD": Decimal("178.40"),
    "SPY": Decimal("718.00"),
    "QQQ": Decimal("498.20"),
    "SOXL": Decimal("32.10"),
    "TSLA": Decimal("245.00"),
    "MSFT": Decimal("445.80"),
    "AAPL": Decimal("228.50"),
    "META": Decimal("612.00"),
    "GOOGL": Decimal("182.30"),
}

DEFAULT_BASELINE = Decimal("100.00")
RISK_FREE_RATE = 0.05
ATM_IV_BASELINE = 0.30


def _to_decimal(value: float, places: str = "0.01") -> Decimal:
    return Decimal(str(round(value, 4))).quantize(Decimal(places))


def _strike_spacing(spot: Decimal) -> Decimal:
    spot_f = float(spot)
    if spot_f < 50:
        return Decimal("0.50")
    if spot_f < 200:
        return Decimal("1.00")
    if spot_f < 500:
        return Decimal("2.50")
    return Decimal("5.00")


def _occ_symbol(ticker: str, exp: date, contract_type: str, strike: Decimal) -> str:
    type_char = "C" if contract_type == "call" else "P"
    strike_int = int(strike * 1000)
    return f"{ticker}{exp:%y%m%d}{type_char}{strike_int:08d}"


def _next_friday(d: date) -> date:
    days_ahead = (4 - d.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return d + timedelta(days=days_ahead)


def _generate_expirations(today: date) -> list[date]:
    """Six weeklies + next two monthly thirds. Dedup."""
    expirations: list[date] = []
    cursor = today
    for _ in range(6):
        cursor = _next_friday(cursor)
        expirations.append(cursor)
    for month_offset in (1, 2):
        month = today.month + month_offset
        year = today.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        first = date(year, month, 1)
        first_friday = first + timedelta(days=(4 - first.weekday()) % 7)
        third_friday = first_friday + timedelta(days=14)
        if third_friday not in expirations:
            expirations.append(third_friday)
    return sorted(set(expirations))


def _bs_greeks(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    contract_type: str,
) -> dict[str, float]:
    """Black-Scholes-Merton Greeks. Returns delta, gamma, theta(per day), vega, rho."""
    if dte <= 0 or iv <= 0:
        # Degenerate: deep ITM/OTM at expiry, return reasonable degenerates
        if contract_type == "call":
            delta = 1.0 if spot > strike else 0.0
        else:
            delta = -1.0 if spot < strike else 0.0
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    T = dte / 365.0
    sqrt_T = np.sqrt(T)
    d1 = (np.log(spot / strike) + (RISK_FREE_RATE + 0.5 * iv * iv) * T) / (iv * sqrt_T)
    d2 = d1 - iv * sqrt_T
    pdf_d1 = norm.pdf(d1)
    cdf_d1 = norm.cdf(d1)
    cdf_d2 = norm.cdf(d2)

    gamma = pdf_d1 / (spot * iv * sqrt_T)
    vega = spot * pdf_d1 * sqrt_T / 100.0  # per 1% change in IV

    if contract_type == "call":
        delta = cdf_d1
        theta_year = -(spot * pdf_d1 * iv) / (2 * sqrt_T) - (
            RISK_FREE_RATE * strike * np.exp(-RISK_FREE_RATE * T) * cdf_d2
        )
        rho = strike * T * np.exp(-RISK_FREE_RATE * T) * cdf_d2 / 100.0
    else:
        delta = cdf_d1 - 1.0
        theta_year = -(spot * pdf_d1 * iv) / (2 * sqrt_T) + (
            RISK_FREE_RATE * strike * np.exp(-RISK_FREE_RATE * T) * norm.cdf(-d2)
        )
        rho = -strike * T * np.exp(-RISK_FREE_RATE * T) * norm.cdf(-d2) / 100.0

    theta_day = theta_year / 365.0

    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "theta": float(theta_day),
        "vega": float(vega),
        "rho": float(rho),
    }


def _bs_price(spot: float, strike: float, dte: int, iv: float, contract_type: str) -> float:
    if dte <= 0:
        if contract_type == "call":
            return max(spot - strike, 0.0)
        return max(strike - spot, 0.0)
    T = dte / 365.0
    sqrt_T = np.sqrt(T)
    d1 = (np.log(spot / strike) + (RISK_FREE_RATE + 0.5 * iv * iv) * T) / (iv * sqrt_T)
    d2 = d1 - iv * sqrt_T
    if contract_type == "call":
        return float(spot * norm.cdf(d1) - strike * np.exp(-RISK_FREE_RATE * T) * norm.cdf(d2))
    return float(strike * np.exp(-RISK_FREE_RATE * T) * norm.cdf(-d2) - spot * norm.cdf(-d1))


class MockDataClient(MarketDataClient):
    def __init__(
        self,
        seed: int = 42,
        baseline_prices: dict[str, Decimal] | None = None,
    ) -> None:
        self._seed = seed
        self._rng: Generator = np.random.default_rng(seed)
        self._baselines: dict[str, Decimal] = {**DEFAULT_BASELINES, **(baseline_prices or {})}
        self._injected_quotes: dict[str, Quote] = {}
        self._market_open_override: bool | None = None
        self._call_count: dict[str, int] = {}

    def reset(self) -> None:
        """Restore deterministic seed state. Call between test cases."""
        self._rng = np.random.default_rng(self._seed)
        self._injected_quotes.clear()
        self._market_open_override = None
        self._call_count.clear()

    def set_market_status(self, is_open: bool) -> None:
        """Force market open/closed for testing."""
        self._market_open_override = is_open

    def inject_quote(self, ticker: str, quote: Quote) -> None:
        """Override the next get_quote response for `ticker`."""
        self._injected_quotes[ticker] = quote

    def _baseline(self, ticker: str) -> Decimal:
        return self._baselines.get(ticker, DEFAULT_BASELINE)

    def _is_market_open(self) -> bool:
        if self._market_open_override is not None:
            return self._market_open_override
        now = datetime.now(UTC)
        weekday = now.weekday()
        if weekday >= 5:  # Sat/Sun
            return False
        # 13:30-20:00 UTC ~= 9:30-16:00 ET (without DST nuance)
        return time(13, 30) <= now.time() <= time(20, 0)

    def _spot_for(self, ticker: str) -> Decimal:
        baseline = self._baseline(ticker)
        # ±0.5% drift on each call
        drift = self._rng.normal(0.0, 0.005)
        spot = float(baseline) * (1.0 + drift)
        return _to_decimal(spot)

    def _avg_volume(self, ticker: str) -> int:
        # Large-cap default, ETFs get bumped
        if ticker in {"SPY", "QQQ"}:
            return 80_000_000
        if ticker in {"TSLA", "NVDA", "AMD", "SOXL"}:
            return 120_000_000
        return 60_000_000

    async def get_quote(self, ticker: str) -> Quote:
        if ticker in self._injected_quotes:
            quote = self._injected_quotes.pop(ticker)
            return quote

        ticker = ticker.upper()
        baseline = self._baseline(ticker)
        spot = self._spot_for(ticker)
        spread_pct = self._rng.uniform(0.0005, 0.0015)
        half_spread = float(spot) * spread_pct / 2
        bid = _to_decimal(float(spot) - half_spread)
        ask = _to_decimal(float(spot) + half_spread)
        prev_close = _to_decimal(float(baseline) * (1.0 + self._rng.normal(0.0, 0.01)))
        day_open = _to_decimal(float(prev_close) * (1.0 + self._rng.normal(0.0, 0.003)))
        high_jitter = abs(self._rng.normal(0.0, 0.005))
        low_jitter = abs(self._rng.normal(0.0, 0.005))
        day_high = _to_decimal(max(float(spot), float(day_open)) * (1.0 + high_jitter))
        day_low = _to_decimal(min(float(spot), float(day_open)) * (1.0 - low_jitter))
        avg_vol = self._avg_volume(ticker)
        # intraday volume scaled by time-of-day-ish
        volume = int(avg_vol * self._rng.uniform(0.4, 1.4))

        return Quote(
            ticker=ticker,
            spot=spot,
            bid=bid,
            ask=ask,
            bid_size=int(self._rng.integers(1, 50)),
            ask_size=int(self._rng.integers(1, 50)),
            day_open=day_open,
            day_high=day_high,
            day_low=day_low,
            prev_close=prev_close,
            volume=volume,
            avg_volume_30d=avg_vol,
            is_market_open=self._is_market_open(),
            timestamp=datetime.now(UTC),
        )

    async def get_quotes(self, tickers: list[str]) -> dict[str, Quote]:
        return {t.upper(): await self.get_quote(t) for t in tickers}

    async def get_bars(
        self,
        ticker: str,
        timeframe: Timeframe,
        limit: int = 200,
        end: datetime | None = None,
    ) -> list[Bar]:
        ticker = ticker.upper()
        baseline = float(self._baseline(ticker))
        end_ts = end or datetime.now(UTC)
        delta_map: dict[Timeframe, timedelta] = {
            "1m": timedelta(minutes=1),
            "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15),
            "1h": timedelta(hours=1),
            "1d": timedelta(days=1),
        }
        step = delta_map[timeframe]
        # Random walk backwards from current spot
        prices = [baseline * (1.0 + self._rng.normal(0.0, 0.005))]
        for _ in range(limit - 1):
            last = prices[-1]
            prices.append(last * (1.0 + self._rng.normal(0.0, 0.003)))
        prices.reverse()  # ascending time-order

        bars: list[Bar] = []
        for i, close in enumerate(prices):
            ts = end_ts - step * (limit - 1 - i)
            open_p = close * (1.0 + self._rng.normal(0.0, 0.001))
            high_p = max(open_p, close) * (1.0 + abs(self._rng.normal(0.0, 0.002)))
            low_p = min(open_p, close) * (1.0 - abs(self._rng.normal(0.0, 0.002)))
            vol = int(self._rng.integers(50_000, 500_000))
            vwap = (open_p + close + high_p + low_p) / 4.0 if timeframe != "1d" else None
            bars.append(
                Bar(
                    timestamp=ts,
                    open=_to_decimal(open_p),
                    high=_to_decimal(high_p),
                    low=_to_decimal(low_p),
                    close=_to_decimal(close),
                    volume=vol,
                    vwap=_to_decimal(vwap) if vwap is not None else None,
                )
            )
        return bars

    async def get_options_chain(
        self,
        ticker: str,
        min_dte: int | None = None,
        max_dte: int | None = None,
        contract_type: ContractTypeFilter = "both",
    ) -> OptionsChain:
        ticker = ticker.upper()
        spot = self._spot_for(ticker)
        spot_f = float(spot)
        spacing = _strike_spacing(spot)
        spacing_f = float(spacing)
        atm = round(spot_f / spacing_f) * spacing_f
        strikes = [Decimal(str(atm + (i - 10) * spacing_f)) for i in range(21)]
        today = datetime.now(UTC).date()
        expirations = _generate_expirations(today)

        types_to_make: list[ContractType] = []
        if contract_type in ("call", "both"):
            types_to_make.append("call")
        if contract_type in ("put", "both"):
            types_to_make.append("put")

        contracts: list[OptionContract] = []
        for exp in expirations:
            dte = (exp - today).days
            if min_dte is not None and dte < min_dte:
                continue
            if max_dte is not None and dte > max_dte:
                continue
            for k in strikes:
                k_f = float(k)
                # IV smile: ATM lower, OTM higher; puts tilt up
                moneyness = (k_f - spot_f) / spot_f
                base_iv = ATM_IV_BASELINE + 0.10 * abs(moneyness)
                for ctype in types_to_make:
                    iv = base_iv + (0.05 if ctype == "put" and moneyness < 0 else 0.0)
                    iv = max(iv + self._rng.normal(0.0, 0.01), 0.05)
                    greeks = _bs_greeks(spot_f, k_f, dte, iv, ctype)
                    price = _bs_price(spot_f, k_f, dte, iv, ctype)
                    spread = max(price * 0.02, 0.05)
                    bid = max(price - spread / 2, 0.01)
                    ask = price + spread / 2
                    # OI peak ATM, decays outward
                    distance = abs(k_f - spot_f) / max(spot_f * 0.05, 1.0)
                    oi_base = 5000 * np.exp(-(distance**2) / 4)
                    oi = int(oi_base * self._rng.uniform(0.5, 1.5))
                    vol = int(oi * self._rng.uniform(0.05, 0.25))
                    contracts.append(
                        OptionContract(
                            symbol=_occ_symbol(ticker, exp, ctype, k),
                            underlying=ticker,
                            underlying_spot=spot,
                            expiration=exp,
                            dte=dte,
                            strike=k,
                            contract_type=ctype,
                            bid=_to_decimal(bid),
                            ask=_to_decimal(ask),
                            last=_to_decimal(price),
                            volume=vol,
                            open_interest=oi,
                            iv=Decimal(str(round(iv, 4))),
                            delta=Decimal(str(round(greeks["delta"], 4))),
                            gamma=Decimal(str(round(greeks["gamma"], 6))),
                            theta=Decimal(str(round(greeks["theta"], 4))),
                            vega=Decimal(str(round(greeks["vega"], 4))),
                            rho=Decimal(str(round(greeks["rho"], 4))),
                        )
                    )

        return OptionsChain(
            underlying=ticker,
            spot_at_fetch=spot,
            contracts=contracts,
            timestamp=datetime.now(UTC),
        )

    async def get_account_state(self) -> AccountState:
        return AccountState(
            account_id="MOCK-ACCOUNT-0001",
            buying_power=Decimal("100000.00"),
            cash=Decimal("100000.00"),
            equity=Decimal("100000.00"),
            pdt_count_remaining=3,
            is_pdt=False,
            margin_buying_power=None,
            positions_count=0,
            timestamp=datetime.now(UTC),
        )

    def _mover_entry(self, ticker: str, category: MoverCategory) -> MoverEntry:
        baseline = self._baselines[ticker]
        if category == "top_gainer":
            change_pct = float(abs(self._rng.normal(0.0, 3.0)) + 1.0)
        elif category == "top_loser":
            change_pct = float(-abs(self._rng.normal(0.0, 3.0)) - 1.0)
        else:
            change_pct = float(self._rng.normal(0.0, 3.0))
        last_price = float(baseline) * (1.0 + change_pct / 100.0)
        return MoverEntry(
            ticker=ticker,
            last=_to_decimal(last_price),
            change_pct=Decimal(str(round(change_pct, 2))),
            volume=int(self._rng.integers(1_000_000, 200_000_000)),
            category=category,
        )

    async def get_movers(self) -> Movers:
        tickers = list(self._baselines.keys())[:10]
        return Movers(
            most_active=[self._mover_entry(t, "most_active") for t in tickers],
            top_gainers=[self._mover_entry(t, "top_gainer") for t in tickers],
            top_losers=[self._mover_entry(t, "top_loser") for t in tickers],
            timestamp=datetime.now(UTC),
        )

    async def get_market_status(self) -> MarketStatus:
        is_open = self._is_market_open()
        now = datetime.now(UTC)
        # Simple next-session math: today 13:30 UTC if before, else next weekday 13:30
        today_open = datetime.combine(now.date(), time(13, 30), tzinfo=UTC)
        today_close = datetime.combine(now.date(), time(20, 0), tzinfo=UTC)
        if now < today_open:
            next_open = today_open
            next_close = today_close
        elif now < today_close:
            next_open = today_open + timedelta(days=1)
            next_close = today_close
        else:
            next_open = today_open + timedelta(days=1)
            next_close = today_close + timedelta(days=1)

        return MarketStatus(
            is_open=is_open,
            is_pre_market=not is_open and time(8, 0) <= now.time() < time(13, 30),
            is_post_market=not is_open and time(20, 0) <= now.time() <= time(24, 0),
            next_open=next_open,
            next_close=next_close,
            timestamp=now,
        )

    async def health_check(self) -> bool:
        return True
