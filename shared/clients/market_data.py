from abc import ABC, abstractmethod
from datetime import datetime
from typing import Literal

from shared.schemas.market import (
    AccountState,
    Bar,
    MarketStatus,
    Movers,
    OptionsChain,
    Quote,
)

Timeframe = Literal["1m", "5m", "15m", "1h", "1d"]
ContractTypeFilter = Literal["call", "put", "both"]


class MarketDataClient(ABC):
    """Abstract market data provider. Mock and Schwab impls share this contract."""

    @abstractmethod
    async def get_quote(self, ticker: str) -> Quote: ...

    @abstractmethod
    async def get_quotes(self, tickers: list[str]) -> dict[str, Quote]: ...

    @abstractmethod
    async def get_bars(
        self,
        ticker: str,
        timeframe: Timeframe,
        limit: int = 200,
        end: datetime | None = None,
    ) -> list[Bar]: ...

    @abstractmethod
    async def get_options_chain(
        self,
        ticker: str,
        min_dte: int | None = None,
        max_dte: int | None = None,
        contract_type: ContractTypeFilter = "both",
    ) -> OptionsChain: ...

    @abstractmethod
    async def get_account_state(self) -> AccountState: ...

    @abstractmethod
    async def get_movers(self) -> Movers: ...

    @abstractmethod
    async def get_market_status(self) -> MarketStatus: ...

    @abstractmethod
    async def health_check(self) -> bool: ...
