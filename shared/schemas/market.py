from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

ContractType = Literal["call", "put"]
MoverCategory = Literal["most_active", "top_gainer", "top_loser"]


class Quote(BaseModel):
    """Current market snapshot for a single ticker. UTC timestamps, Decimal prices."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    spot: Decimal
    bid: Decimal
    ask: Decimal
    bid_size: int
    ask_size: int
    day_open: Decimal
    day_high: Decimal
    day_low: Decimal
    prev_close: Decimal
    volume: int
    avg_volume_30d: int
    is_market_open: bool
    timestamp: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def day_change(self) -> Decimal:
        return self.spot - self.prev_close

    @computed_field  # type: ignore[prop-decorator]
    @property
    def day_change_pct(self) -> Decimal:
        if self.prev_close == 0:
            return Decimal("0")
        return ((self.spot - self.prev_close) / self.prev_close) * Decimal("100")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def volume_vs_avg(self) -> Decimal:
        if self.avg_volume_30d == 0:
            return Decimal("0")
        return Decimal(self.volume) / Decimal(self.avg_volume_30d)


class Bar(BaseModel):
    """Single OHLCV bar. VWAP populated for intraday only."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    vwap: Decimal | None = None


class OptionContract(BaseModel):
    """Single options contract with snapshot of underlying spot at fetch time."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    underlying: str
    underlying_spot: Decimal
    expiration: date
    dte: int
    strike: Decimal
    contract_type: ContractType
    bid: Decimal
    ask: Decimal
    last: Decimal | None
    volume: int
    open_interest: int
    iv: Decimal
    delta: Decimal
    gamma: Decimal
    theta: Decimal
    vega: Decimal
    rho: Decimal
    # Phase 8.7g — additional Schwab fields surfaced for the option_chain tool.
    # All default to safe values so existing call sites and stored IV snapshots
    # don't need migration.
    mark: Decimal | None = None
    bid_size: int = 0
    ask_size: int = 0
    theoretical_value: Decimal | None = None
    expiration_type: str | None = None
    is_non_standard: bool = False
    percent_change: Decimal | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def intrinsic_value(self) -> Decimal:
        zero = Decimal("0")
        if self.contract_type == "call":
            return max(self.underlying_spot - self.strike, zero)
        return max(self.strike - self.underlying_spot, zero)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def extrinsic_value(self) -> Decimal:
        return max(self.mid - self.intrinsic_value, Decimal("0"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def spread_pct(self) -> Decimal:
        if self.mid == 0:
            return Decimal("0")
        return ((self.ask - self.bid) / self.mid) * Decimal("100")


class OptionsChain(BaseModel):
    """Full options chain for a ticker with helper filters."""

    model_config = ConfigDict(frozen=True)

    underlying: str
    spot_at_fetch: Decimal
    contracts: list[OptionContract]
    timestamp: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def expirations(self) -> list[date]:
        return sorted({c.expiration for c in self.contracts})

    def for_expiration(self, exp: date) -> list[OptionContract]:
        return [c for c in self.contracts if c.expiration == exp]

    def for_dte_range(self, min_dte: int, max_dte: int) -> list[OptionContract]:
        return [c for c in self.contracts if min_dte <= c.dte <= max_dte]

    def calls_only(self) -> list[OptionContract]:
        return [c for c in self.contracts if c.contract_type == "call"]

    def puts_only(self) -> list[OptionContract]:
        return [c for c in self.contracts if c.contract_type == "put"]

    def for_strike_range(
        self, min_strike: Decimal, max_strike: Decimal
    ) -> list[OptionContract]:
        return [c for c in self.contracts if min_strike <= c.strike <= max_strike]


class AccountState(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: str
    buying_power: Decimal
    cash: Decimal
    equity: Decimal
    pdt_count_remaining: int
    is_pdt: bool
    margin_buying_power: Decimal | None
    positions_count: int
    timestamp: datetime


class MoverEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    last: Decimal
    change_pct: Decimal
    volume: int
    category: MoverCategory


class Movers(BaseModel):
    model_config = ConfigDict(frozen=True)

    most_active: list[MoverEntry] = Field(default_factory=list)
    top_gainers: list[MoverEntry] = Field(default_factory=list)
    top_losers: list[MoverEntry] = Field(default_factory=list)
    timestamp: datetime


class MarketStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_open: bool
    is_pre_market: bool
    is_post_market: bool
    next_open: datetime
    next_close: datetime
    timestamp: datetime
