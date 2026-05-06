from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_PATH: str
    LOG_LEVEL: str = "info"
    ENVIRONMENT: Literal["dev", "paper", "live"] = "dev"

    DATA_CLIENT: Literal["mock", "schwab"] = "mock"
    MOCK_SEED: int = 42

    SCHWAB_CLIENT_ID: str | None = None
    SCHWAB_CLIENT_SECRET: str | None = None
    SCHWAB_REDIRECT_URI: str = "https://127.0.0.1:8443"
    SCHWAB_TOKEN_PATH: str = "/data/schwab_token.json"

    FINNHUB_API_KEY: str | None = None
    EXA_API_KEY: str | None = None
    NTFY_TOPIC: str | None = None
    API_BEARER_TOKEN: str | None = None


settings = Settings()  # type: ignore[call-arg]
