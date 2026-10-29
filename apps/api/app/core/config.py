"""Application settings loaded from environment variables.

All secrets come from the environment; nothing sensitive is hardcoded.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SALESIQ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    service_name: str = "salesiq-api"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "postgresql+psycopg://salesiq:salesiq@127.0.0.1:55432/salesiq"
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_connect_timeout_s: int = Field(default=5, ge=1, le=60)

    redis_url: str = "redis://127.0.0.1:56379/0"

    # Used for session signing in Phase 2; must be overridden outside development.
    secret_key: SecretStr = SecretStr("dev-insecure-change-me")

    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate_for_runtime(self) -> None:
        """Refuse to boot non-development environments with insecure defaults."""
        if self.environment in ("staging", "production"):
            if self.secret_key.get_secret_value() == "dev-insecure-change-me":
                raise RuntimeError("SALESIQ_SECRET_KEY must be set outside development")
            if len(self.secret_key.get_secret_value()) < 32:
                raise RuntimeError("SALESIQ_SECRET_KEY must be at least 32 characters")


@lru_cache
def get_settings() -> Settings:
    return Settings()
