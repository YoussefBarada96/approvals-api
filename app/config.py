from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, read from environment variables (and a local .env file)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://approvals:approvals@localhost:5432/approvals"


@lru_cache
def get_settings() -> Settings:
    return Settings()
