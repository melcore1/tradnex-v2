from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_PATH: str
    LOG_LEVEL: str = "info"
    ENVIRONMENT: Literal["dev", "paper", "live"] = "dev"

    SCHWAB_CLIENT_ID: str | None = None
    SCHWAB_CLIENT_SECRET: str | None = None
    SCHWAB_REDIRECT_URI: str | None = None
    FINNHUB_API_KEY: str | None = None
    EXA_API_KEY: str | None = None
    NTFY_TOPIC: str | None = None
    API_BEARER_TOKEN: str | None = None


settings = Settings()  # type: ignore[call-arg]
