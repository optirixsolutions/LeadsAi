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

    # The API connects as a non-owner, non-superuser role so row-level security applies.
    database_url: str = "postgresql+psycopg://salesiq_app:salesiq_app@127.0.0.1:55432/salesiq"
    # Migrations run as the schema owner. Falls back to database_url when unset.
    migration_database_url: str | None = (
        "postgresql+psycopg://salesiq:salesiq@127.0.0.1:55432/salesiq"
    )
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_connect_timeout_s: int = Field(default=5, ge=1, le=60)

    redis_url: str = "redis://127.0.0.1:56379/0"

    # Signs CSRF tokens; must be overridden outside development.
    secret_key: SecretStr = SecretStr("dev-insecure-change-me")

    cors_origins: list[str] = ["http://localhost:3000"]
    # Public base URL of the web app, used to build links in emails.
    web_base_url: str = "http://localhost:3000"

    registration_enabled: bool = True
    session_ttl_hours: int = Field(default=24 * 14, ge=1, le=24 * 90)
    session_idle_timeout_hours: int = Field(default=24, ge=1, le=24 * 30)
    invitation_ttl_hours: int = Field(default=24 * 7, ge=1, le=24 * 30)
    password_reset_ttl_minutes: int = Field(default=30, ge=5, le=24 * 60)
    email_verification_ttl_hours: int = Field(default=48, ge=1, le=24 * 14)
    login_rate_limit_per_minute: int = Field(default=10, ge=1, le=1000)

    # "log" prints emails to the log in development only; "disabled" drops them.
    mailer: Literal["log", "memory", "disabled"] = "log"

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cookie_secure(self) -> bool:
        return self.environment in ("staging", "production")

    @property
    def effective_migration_url(self) -> str:
        return self.migration_database_url or self.database_url

    def validate_for_runtime(self) -> None:
        """Refuse to boot non-development environments with insecure defaults."""
        if self.environment in ("staging", "production"):
            if self.secret_key.get_secret_value() == "dev-insecure-change-me":
                raise RuntimeError("SALESIQ_SECRET_KEY must be set outside development")
            if len(self.secret_key.get_secret_value()) < 32:
                raise RuntimeError("SALESIQ_SECRET_KEY must be at least 32 characters")
            if self.mailer != "disabled":
                raise RuntimeError(
                    "Only SALESIQ_MAILER=disabled is allowed until a real mailer exists"
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
