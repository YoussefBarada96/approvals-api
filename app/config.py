from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-secret-change-me-0123456789"


class Settings(BaseSettings):
    """App settings, read from environment variables (and a local .env file)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://approvals:approvals@localhost:5432/approvals"

    # HS256 keys should be at least 256 bits (RFC 7518, section 3.2).
    jwt_secret: SecretStr = Field(default=SecretStr(DEV_JWT_SECRET), min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    worker_poll_seconds: float = Field(default=30, gt=0)
    worker_batch_size: int = Field(default=50, ge=1, le=1000)

    @model_validator(mode="after")
    def require_real_secret_outside_development(self) -> "Settings":
        # Refuse to start with the well-known dev secret anywhere it could
        # matter: anyone who has read this repo could forge tokens with it.
        if self.app_env != "development" and self.jwt_secret.get_secret_value() == DEV_JWT_SECRET:
            raise ValueError("JWT_SECRET must be set outside development")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
