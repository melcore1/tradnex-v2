from shared.clients.halt_feed import HaltFeed
from shared.clients.market_data import MarketDataClient
from shared.clients.mock_halt_feed import MockHaltFeed
from shared.clients.mock_market_data import MockDataClient
from shared.clients.nasdaq_halt_feed import NasdaqHaltFeed
from shared.clients.schwab_market_data import SchwabDataClient
from shared.config import Settings


def make_market_data_client(config: Settings) -> MarketDataClient:
    """Construct the market-data client selected by Settings.DATA_CLIENT."""
    match config.DATA_CLIENT:
        case "mock":
            return MockDataClient(seed=config.MOCK_SEED)
        case "schwab":
            if not config.SCHWAB_CLIENT_ID or not config.SCHWAB_CLIENT_SECRET:
                raise ValueError(
                    "DATA_CLIENT=schwab but SCHWAB_CLIENT_ID/SECRET are empty. "
                    "Add credentials to .env or set DATA_CLIENT=mock."
                )
            return SchwabDataClient(
                client_id=config.SCHWAB_CLIENT_ID,
                client_secret=config.SCHWAB_CLIENT_SECRET,
                redirect_uri=config.SCHWAB_REDIRECT_URI,
                token_path=config.SCHWAB_TOKEN_PATH,
            )
        case _:
            raise ValueError(f"Unknown DATA_CLIENT: {config.DATA_CLIENT}")


def make_halt_feed(config: Settings) -> HaltFeed:
    """Construct the halt feed selected by Settings.HALT_FEED."""
    match config.HALT_FEED:
        case "mock":
            return MockHaltFeed()
        case "nasdaq":
            return NasdaqHaltFeed(
                poll_interval_seconds=config.HALT_POLL_MARKET_SECONDS,
            )
        case _:
            raise ValueError(f"Unknown HALT_FEED: {config.HALT_FEED}")
