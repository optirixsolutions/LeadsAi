"""Integration connections, webhook events, usage records, and subscriptions."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


def _org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )


def _user_fk() -> Mapped[uuid.UUID | None]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))


class ConnectionKind(enum.StrEnum):
    email_smtp = "email_smtp"


class ConnectionHealth(enum.StrEnum):
    unknown = "unknown"
    ok = "ok"
    failing = "failing"


class UsageKind(enum.StrEnum):
    workflow_run = "workflow_run"
    model_tokens = "model_tokens"


class IntegrationConnection(IdMixin, Base):
    """A provider an organization has connected. Secrets are encrypted, and removed with it."""

    __tablename__ = "integration_connections"
    __table_args__ = (
        Index(
            "uq_integration_connections_active_kind",
            "organization_id",
            "kind",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    kind: Mapped[ConnectionKind] = mapped_column(
        _enum(ConnectionKind, "integration_kind"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # Host, port, and other settings that are not secret.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    encrypted_password: Mapped[str | None] = mapped_column(Text)
    encrypted_webhook_secret: Mapped[str | None] = mapped_column(Text)
    health: Mapped[ConnectionHealth] = mapped_column(
        _enum(ConnectionHealth, "integration_health"), nullable=False
    )
    last_error_category: Mapped[str | None] = mapped_column(String(40))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WebhookEvent(IdMixin, Base):
    """A signed event from a provider. The unique key makes a replay harmless. No payload is kept,
    because all that is needed is what it did."""

    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("connection_id", "event_id"),)

    organization_id: Mapped[uuid.UUID] = _org_fk()
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(255))
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deliveries.id", ondelete="SET NULL")
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UsageRecord(IdMixin, Base):
    """Append-only. Costs are estimates, unless a provider's billing data ever says otherwise."""

    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_records_org_kind_at", "organization_id", "kind", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    kind: Mapped[UsageKind] = mapped_column(_enum(UsageKind, "usage_kind"), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    model_key: Mapped[str | None] = mapped_column(String(80))
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Subscription(Base):
    """Which plan an organization is on. With no row, it is on the default plan."""

    __tablename__ = "subscriptions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    plan_key: Mapped[str] = mapped_column(String(40), nullable=False)
    # Where this came from. Only "development" exists until a payment provider is connected.
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
