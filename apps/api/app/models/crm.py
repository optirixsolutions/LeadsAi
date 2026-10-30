"""Lead and CRM domain: companies, leads, activities, imports, pipeline, opportunities.

Every table carries `organization_id` and is protected by row-level security.
Leads are soft-deleted (`deleted_at`) so history and audit references survive.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


def _org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )


class LeadStatus(enum.StrEnum):
    new = "new"
    contacted = "contacted"
    qualified = "qualified"
    disqualified = "disqualified"


class StageKind(enum.StrEnum):
    open = "open"
    won = "won"
    lost = "lost"


class ActivityType(enum.StrEnum):
    created = "created"
    imported = "imported"
    updated = "updated"
    status_changed = "status_changed"
    assigned = "assigned"
    note = "note"
    opportunity_created = "opportunity_created"
    stage_changed = "stage_changed"
    deleted = "deleted"
    research_added = "research_added"
    assessed = "assessed"


class ImportStatus(enum.StrEnum):
    completed = "completed"
    failed = "failed"


class DuplicatePolicy(enum.StrEnum):
    skip = "skip"
    update = "update"


class Company(IdMixin, TimestampMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (
        # Domains are stored normalized (lowercase, no scheme/www); one company per domain.
        Index(
            "uq_companies_org_domain",
            "organization_id",
            "domain",
            unique=True,
            postgresql_where=text("domain IS NOT NULL"),
        ),
        Index("ix_companies_org_name", "organization_id", func.lower(text("name"))),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(253))
    industry: Mapped[str | None] = mapped_column(String(120))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    country: Mapped[str | None] = mapped_column(String(80))


class LeadImport(IdMixin, Base):
    """One CSV import. The idempotency key makes resubmitting the same file a no-op."""

    __tablename__ = "lead_imports"
    __table_args__ = (UniqueConstraint("organization_id", "idempotency_key"),)

    organization_id: Mapped[uuid.UUID] = _org_fk()
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ImportStatus] = mapped_column(_enum(ImportStatus, "import_status"))
    duplicate_policy: Mapped[DuplicatePolicy] = mapped_column(
        _enum(DuplicatePolicy, "duplicate_policy")
    )
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # First N row errors: [{"row": int, "error": str}]
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Lead(IdMixin, TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        # Duplicate detection key: one live lead per normalized email per org.
        Index(
            "uq_leads_org_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index("ix_leads_org_created", "organization_id", "created_at"),
        Index("ix_leads_org_status", "organization_id", "status"),
        Index("ix_leads_org_owner", "organization_id", "owner_user_id"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead_imports.id", ondelete="SET NULL")
    )
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(320))
    title: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40))
    linkedin_url: Mapped[str | None] = mapped_column(String(400))
    source: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[LeadStatus] = mapped_column(
        _enum(LeadStatus, "lead_status"), nullable=False, default=LeadStatus.new
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), nullable=False, default=list, server_default="{}"
    )
    custom_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PipelineStage(IdMixin, Base):
    __tablename__ = "pipeline_stages"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[StageKind] = mapped_column(_enum(StageKind, "stage_kind"), nullable=False)


class Opportunity(IdMixin, TimestampMixin, Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        Index("ix_opportunities_org_stage", "organization_id", "stage_id"),
        CheckConstraint("amount IS NULL OR amount >= 0", name="amount_non_negative"),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    stage_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_stages.id", ondelete="RESTRICT"), nullable=False
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL")
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    # Set when the opportunity enters a won/lost stage; cleared if it is reopened.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Activity(IdMixin, Base):
    """Append-only timeline entry for a lead and/or opportunity."""

    __tablename__ = "activities"
    __table_args__ = (
        Index("ix_activities_lead_created", "lead_id", "created_at"),
        Index("ix_activities_opportunity", "opportunity_id"),
        CheckConstraint("lead_id IS NOT NULL OR opportunity_id IS NOT NULL", name="has_subject"),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE")
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id", ondelete="CASCADE")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    type: Mapped[ActivityType] = mapped_column(_enum(ActivityType, "activity_type"))
    body: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


DEFAULT_STAGES: list[tuple[str, StageKind]] = [
    ("Qualification", StageKind.open),
    ("Discovery", StageKind.open),
    ("Proposal", StageKind.open),
    ("Negotiation", StageKind.open),
    ("Closed won", StageKind.won),
    ("Closed lost", StageKind.lost),
]
