"""FastAPI application entry point.

Run via:
    uvicorn services.api.main:app --host 0.0.0.0 --port 8080

Routers are mounted under /api/*. OpenAPI docs are publicly accessible at
/api/docs (Swagger), /api/redoc (ReDoc), /api/openapi.json.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.api.middleware import (
    RequestLoggingMiddleware,
    SessionAuthMiddleware,
)
from services.api.routers import (
    auth,
    candidates,
    credentials,
    dashboard,
    evaluations,
    events,
    positions,
    prompts,
    system,
    universe,
    watchlist,
)
from services.api.routers import settings as settings_router
from shared.config import settings
from shared.db import get_connection, run_migrations
from shared.events import emit
from shared.services.credentials import migrate_env_credentials
from shared.services.encryption import (
    EncryptionService,
    InvalidEncryptionKeyError,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: apply migrations, run env→DB credential migration, warn if
    no users exist."""
    applied = run_migrations()
    if applied:
        emit("api", "info", "migrations_applied", {"files": applied})

    # Phase 8a: best-effort env → DB credential migration. Skipped (with a
    # warning) when ENCRYPTION_KEY isn't configured so dev environments
    # without secrets can still boot the API for testing.
    if settings.ENCRYPTION_KEY:
        try:
            encryption = EncryptionService(settings.ENCRYPTION_KEY)
            conn = get_connection()
            try:
                migrated = migrate_env_credentials(conn, encryption)
            finally:
                conn.close()
            if migrated:
                emit(
                    "api",
                    "info",
                    "env_credentials_migrated_summary",
                    {"count": len(migrated), "types": list(migrated)},
                )
        except InvalidEncryptionKeyError as e:
            emit(
                "api",
                "error",
                "encryption_key_invalid",
                {"error": str(e)[:300]},
            )
    else:
        emit(
            "api",
            "warn",
            "encryption_key_missing",
            {
                "hint": (
                    "ENCRYPTION_KEY is not configured. Generate one via "
                    "`python -m services.api.cli generate-encryption-key` "
                    "and add it to .env. Until then, the credentials store "
                    "is unavailable."
                ),
            },
        )

    conn = get_connection()
    try:
        user_count = int(
            conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        )
    finally:
        conn.close()
    if user_count == 0:
        emit(
            "api",
            "warn",
            "no_users_seeded",
            {
                "hint": (
                    "Run `python -m services.api.cli create-user "
                    "--email <you@example.com>` to seed a user before "
                    "logging in."
                ),
            },
        )
    emit(
        "api",
        "info",
        "service_started",
        {
            "host": settings.API_HOST,
            "port": settings.API_PORT,
            "environment": settings.ENVIRONMENT,
            "users_seeded": user_count,
        },
    )
    yield
    emit("api", "info", "service_stopping", {})


app = FastAPI(
    title="TradNex 2 API",
    version="1.0.0",
    description=(
        "Resource-oriented REST + SSE event stream over the TradNex 2 "
        "decision pipeline. Single-user auth via HTTP-only session cookie."
    ),
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS — empty by default = same-origin only. For local dev with a
# frontend on another port, set CORS_ALLOW_ORIGINS in .env.
_cors_origins = [
    o.strip() for o in settings.CORS_ALLOW_ORIGINS.split(",") if o.strip()
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Custom middleware (last-added runs first).
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SessionAuthMiddleware)


@app.get("/api/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness — returns immediately. No DB or auth check."""
    return {"status": "ok"}


@app.get("/api/ready", tags=["meta"])
async def ready() -> dict[str, object]:
    """Readiness — validates DB connectivity + key tables exist."""
    conn = get_connection()
    try:
        ok_users = (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='users'"
            ).fetchone()
            is not None
        )
        ok_candidates = (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='candidates'"
            ).fetchone()
            is not None
        )
    finally:
        conn.close()
    return {
        "status": "ready" if (ok_users and ok_candidates) else "not_ready",
        "checks": {
            "db": True,
            "users_table": ok_users,
            "candidates_table": ok_candidates,
        },
    }


# Routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(candidates.router, prefix="/api/candidates", tags=["candidates"])
app.include_router(positions.router, prefix="/api/positions", tags=["positions"])
app.include_router(evaluations.router, prefix="/api/evaluations", tags=["evaluations"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(universe.router, prefix="/api/universe", tags=["universe"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(prompts.router, prefix="/api/prompts", tags=["prompts"])
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(events.router, prefix="/api/events", tags=["events"])
app.include_router(
    credentials.router, prefix="/api/credentials", tags=["credentials"]
)
