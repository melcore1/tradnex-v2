from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_PATH: str
    LOG_LEVEL: str = "info"
    ENVIRONMENT: Literal["dev", "paper", "live"] = "dev"

    DATA_CLIENT: Literal["mock", "schwab"] = "mock"
    MOCK_SEED: int = 42

    HALT_FEED: Literal["mock", "nasdaq"] = "mock"
    HALT_POLL_MARKET_SECONDS: int = 30
    HALT_POLL_OFF_HOURS_SECONDS: int = 300

    # Phase 8a.5: Schwab credentials migrated to encrypted DB store
    # (`schwab_client` for app creds, `schwab_oauth` for user tokens).
    # The env vars below are kept only so the legacy `scripts/schwab_auth.py`
    # CLI bootstrap still functions; new installs configure via the UI.
    SCHWAB_CLIENT_ID: str | None = None
    SCHWAB_CLIENT_SECRET: str | None = None
    SCHWAB_REDIRECT_URI: str = "https://localhost/api/schwab/oauth/callback"
    SCHWAB_TOKEN_PATH: str = "/data/schwab_token.json"
    SCHWAB_OAUTH_ENABLED: bool = True

    FINNHUB_API_KEY: str | None = None
    EXA_API_KEY: str | None = None
    NTFY_TOPIC: str | None = None
    API_BEARER_TOKEN: str | None = None

    CLAUDE_CLIENT: Literal["mock", "cli"] = "mock"
    CLAUDE_MODEL: str = "claude-opus-4-7"
    CLAUDE_TIMEOUT_SECONDS: int = 90
    CLAUDE_CLI_PATH: str = "claude"

    # Phase 6 — FastAPI
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8080
    SESSION_DURATION_DAYS: int = 30
    SESSION_COOKIE_NAME: str = "tradnex_session"
    SESSION_COOKIE_SECURE: bool = True
    SESSION_COOKIE_SAMESITE: Literal["strict", "lax", "none"] = "strict"
    LOGIN_LOCKOUT_THRESHOLD: int = 5
    LOGIN_LOCKOUT_WINDOW_SECONDS: int = 900  # 15 min
    LOGIN_LOCKOUT_DURATION_SECONDS: int = 3600  # 1 hour
    CORS_ALLOW_ORIGINS: str = ""  # comma-separated; empty = same-origin only
    SSE_POLL_INTERVAL_SECONDS: float = 1.0

    # Phase 8a — encrypted credentials store.
    # Master Fernet key for the credentials table. The ONLY env-resident
    # credential after Phase 8a; all provider keys live in the DB.
    # Generate via `python -m services.api.cli generate-encryption-key`.
    ENCRYPTION_KEY: str = ""


settings = Settings()  # type: ignore[call-arg]
