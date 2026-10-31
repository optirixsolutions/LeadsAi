"""Integration, usage, and plan schemas. No response here ever carries a stored secret."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models import ConnectionHealth, ConnectionKind

Host = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=253, pattern=r"^[A-Za-z0-9.:\-]+$"
    ),
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class SmtpConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    host: Host
    port: int = Field(ge=1, le=65535)
    starttls: bool = True
    username: str | None = Field(default=None, max_length=320)
    password: str | None = Field(default=None, max_length=1024)


class SmtpConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    host: Host | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    starttls: bool | None = None
    username: str | None = Field(default=None, max_length=320)
    # Left out, the password stays as it is. Null removes it.
    password: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def _no_empty_settings(self) -> "SmtpConnectionUpdate":
        for name in ("name", "host", "port", "starttls"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        return self


class ConnectionOut(BaseModel):
    id: uuid.UUID
    kind: ConnectionKind
    name: str
    host: str | None
    port: int | None
    starttls: bool | None
    username: str | None
    has_password: bool
    health: ConnectionHealth
    last_error_category: str | None
    last_checked_at: datetime | None
    created_at: datetime
    # Where a provider should send its events. Knowing this proves nothing without the secret.
    webhook_path: str


class ConnectionCreated(ConnectionOut):
    """The only response that contains the webhook secret."""

    webhook_secret: str


class WebhookSecretOut(BaseModel):
    webhook_secret: str


class ModelServerHealth(BaseModel):
    model_key: str
    available: bool


class IntegrationsOut(BaseModel):
    connections: list[ConnectionOut]
    models: list[ModelServerHealth]
    # Why the server itself cannot send at all, which no connection can change.
    server_blocker: str | None
    integrations_included: bool


class WebhookResult(BaseModel):
    result: str


class UsageMetric(BaseModel):
    metric: str
    label: str
    used: int
    limit: int | None


class PlanOut(BaseModel):
    key: str
    label: str
    integrations: bool


class UsageOut(BaseModel):
    plan: PlanOut
    # "default", or "development" when set through the development adapter.
    source: str
    metrics: list[UsageMetric]
    # An estimate from configured rates. None when no priced model has been used this month.
    estimated_cost_usd: float | None
    plans: list[PlanOut]
    # Whether plans can be switched here. Only in development: there is no payment provider.
    development_billing: bool


class DevPlanChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: Annotated[str, StringConstraints(max_length=40)]
