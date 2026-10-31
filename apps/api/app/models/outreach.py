"""Outreach drafts, the approvals they need, suppression lists, and delivery attempts.

An approval covers exact text for an exact address, tied together by a hash. Changing either one
ends the approval. A delivery row is committed before any connection opens, so a crash can leave
an unknown outcome but never a second email.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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


class DraftStatus(enum.StrEnum):
    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    sending = "sending"
    sent = "sent"
    # The mail server refused the address for good.
    undeliverable = "undeliverable"
    # The connection died at a point where the email may have gone. A person has to say which.
    send_unknown = "send_unknown"
    discarded = "discarded"


class DraftOrigin(enum.StrEnum):
    person = "person"
    agent = "agent"
    # Through a token. A person or a model could be at the other end, so it is checked like a model.
    mcp = "mcp"


class ApprovalStatus(enum.StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    # The text or the address changed after this was requested.
    superseded = "superseded"
    expired = "expired"


class DeliveryStatus(enum.StrEnum):
    sending = "sending"
    # The server took responsibility for it. This does not mean it reached an inbox.
    accepted = "accepted"
    # Refused for now. Nothing was sent, so it can be tried again.
    failed = "failed"
    # Refused for good.
    rejected = "rejected"
    unknown = "unknown"


class SuppressionKind(enum.StrEnum):
    email = "email"
    domain = "domain"


class SuppressionReason(enum.StrEnum):
    opt_out = "opt_out"
    bounced = "bounced"
    manual = "manual"


class OutreachDraft(IdMixin, Base):
    __tablename__ = "outreach_drafts"
    __table_args__ = (
        Index("ix_outreach_drafts_org_created", "organization_id", "created_at"),
        Index("ix_outreach_drafts_lead", "lead_id"),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[DraftStatus] = mapped_column(
        _enum(DraftStatus, "outreach_draft_status"), nullable=False
    )
    origin: Mapped[DraftOrigin] = mapped_column(
        _enum(DraftOrigin, "outreach_draft_origin"), nullable=False
    )
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # What the checks found in model-written text. A person sees these before deciding.
    flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # A link or address from a model has to be taken out by a person.
    needs_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # What has to go before `needs_edit` clears. A person can still add links of their own.
    flagged_contacts: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Evidence behind model-written text, by stored ID.
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    rejection_note: Mapped[str | None] = mapped_column(String(1000))
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="SET NULL"), unique=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    updated_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ApprovalRequest(IdMixin, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("ix_approval_requests_org_status", "organization_id", "status", "created_at"),
        # A draft has at most one approval in force.
        Index(
            "uq_approval_requests_live_draft",
            "draft_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'approved')"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outreach_drafts.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        _enum(ApprovalStatus, "approval_status"), nullable=False
    )
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    requested_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    decided_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    note: Mapped[str | None] = mapped_column(String(1000))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Delivery(IdMixin, Base):
    """One attempt to hand an email to a mail server."""

    __tablename__ = "deliveries"
    __table_args__ = (
        Index("ix_deliveries_org_recipient", "organization_id", "recipient", "created_at"),
        Index("ix_deliveries_draft", "draft_id"),
        # An approval can produce one email. A refused attempt sent nothing, so it does not count.
        Index(
            "uq_deliveries_live_approval",
            "approval_id",
            unique=True,
            postgresql_where=text("status IN ('sending', 'accepted', 'unknown')"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outreach_drafts.id", ondelete="CASCADE"), nullable=False
    )
    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[DeliveryStatus] = mapped_column(
        _enum(DeliveryStatus, "delivery_status"), nullable=False
    )
    adapter: Mapped[str] = mapped_column(String(40), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(255))
    error_category: Mapped[str | None] = mapped_column(String(40))
    sent_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    resolved_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SuppressionEntry(IdMixin, Base):
    """An address or domain that must not be contacted. Removing one keeps the record."""

    __tablename__ = "suppression_entries"
    __table_args__ = (
        Index(
            "uq_suppression_entries_active",
            "organization_id",
            "kind",
            "value",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    kind: Mapped[SuppressionKind] = mapped_column(
        _enum(SuppressionKind, "suppression_kind"), nullable=False
    )
    value: Mapped[str] = mapped_column(String(320), nullable=False)
    reason: Mapped[SuppressionReason] = mapped_column(
        _enum(SuppressionReason, "suppression_reason"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String(200))
    created_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    removed_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OutreachSettings(Base):
    """One row per organization. With no row, or `sends_enabled` off, nothing can be sent."""

    __tablename__ = "outreach_settings"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    sends_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sender_name: Mapped[str | None] = mapped_column(String(120))
    sender_email: Mapped[str | None] = mapped_column(String(320))
    # Commercial email has to carry a postal address in many places.
    postal_address: Mapped[str | None] = mapped_column(String(300))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    # Local hours in which nothing goes out. Equal or empty means no quiet hours.
    quiet_start_hour: Mapped[int | None] = mapped_column(Integer)
    quiet_end_hour: Mapped[int | None] = mapped_column(Integer)
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    recontact_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    updated_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
