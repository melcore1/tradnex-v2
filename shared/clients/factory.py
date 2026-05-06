from shared.clients.calendar_feed import CalendarFeed
from shared.clients.claude_cli import ClaudeCliClient
from shared.clients.exa_news import ExaClient, ExaNewsClient
from shared.clients.finnhub_calendar import FinnhubCalendarClient
from shared.clients.halt_feed import HaltFeed
from shared.clients.market_data import MarketDataClient
from shared.clients.mock_calendar import MockCalendarClient
from shared.clients.mock_claude_cli import MockClaudeCliClient
from shared.clients.mock_exa_news import MockExaClient
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


def make_calendar_client(config: Settings) -> CalendarFeed:
    """Pick mock vs Finnhub based on FINNHUB_API_KEY presence. The mock
    auto-seeds plausible upcoming events; the Finnhub client hits the live
    API and degrades to empty lists on errors."""
    if config.FINNHUB_API_KEY:
        return FinnhubCalendarClient(config.FINNHUB_API_KEY)
    return MockCalendarClient()


def make_exa_client(config: Settings) -> ExaClient:
    """Pick mock vs real Exa based on EXA_API_KEY presence. The mock
    auto-seeds one article per baseline ticker; the real client hits Exa
    /search and degrades to empty lists on errors."""
    if config.EXA_API_KEY:
        return ExaNewsClient(config.EXA_API_KEY)
    return MockExaClient()


def make_claude_client(
    config: Settings,
) -> ClaudeCliClient | MockClaudeCliClient:
    """Pick the Claude client based on Settings.CLAUDE_CLIENT.

    'mock' → MockClaudeCliClient (use inject_response in tests/dev).
    'cli'  → ClaudeCliClient invoking the local `claude -p` subprocess.
    """
    match config.CLAUDE_CLIENT:
        case "mock":
            return MockClaudeCliClient(model=config.CLAUDE_MODEL)
        case "cli":
            return ClaudeCliClient(
                model=config.CLAUDE_MODEL,
                timeout_seconds=config.CLAUDE_TIMEOUT_SECONDS,
                cli_path=config.CLAUDE_CLI_PATH,
            )
        case _:
            raise ValueError(f"Unknown CLAUDE_CLIENT: {config.CLAUDE_CLIENT}")
