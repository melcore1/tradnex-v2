import asyncio
import signal
import sys

from shared.clients.factory import make_market_data_client
from shared.config import settings
from shared.db import run_migrations
from shared.events import emit

SERVICE_NAME = "data"


async def _bootstrap() -> bool:
    applied = run_migrations()
    if applied:
        emit(SERVICE_NAME, "info", "migrations_applied", {"files": applied})
    client = make_market_data_client(settings)
    # In dev with the mock client, lazy-seed 252 days of IV history so iv_rank works.
    if settings.DATA_CLIENT == "mock":
        from shared.clients.mock_market_data import MockDataClient

        if isinstance(client, MockDataClient):
            seeded = client.seed_iv_history()
            if seeded:
                emit(SERVICE_NAME, "info", "mock_iv_history_seeded", {"rows": seeded})
    healthy = await client.health_check()
    emit(
        SERVICE_NAME,
        "info" if healthy else "error",
        "service_started",
        {"client_type": settings.DATA_CLIENT, "healthy": healthy},
    )
    return healthy


def main() -> None:
    healthy = asyncio.run(_bootstrap())
    if not healthy:
        emit(SERVICE_NAME, "error", "health_check_failed", {})
        sys.exit(1)
    signal.pause()


if __name__ == "__main__":
    main()
