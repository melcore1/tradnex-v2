import signal

from shared.config import settings
from shared.db import run_migrations
from shared.events import emit

SERVICE_NAME = "api"


def main() -> None:
    applied = run_migrations()
    if applied:
        emit(SERVICE_NAME, "info", "migrations_applied", {"files": applied})
    emit(SERVICE_NAME, "info", "service_started", {"environment": settings.ENVIRONMENT})
    signal.pause()


if __name__ == "__main__":
    main()
