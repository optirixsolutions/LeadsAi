"""Sales intelligence: ICP versions, research evidence, assessments, and research briefs.

Provenance is protected in the database: the app role can only insert ICP versions, and can
update just the review columns of evidence and assessments. Every table is under RLS.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


def _org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )


def _lead_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )


def _user_fk() -> Mapped[uuid.UUID | None]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EvidenceSource(enum.StrEnum):
    manual_note = "manual_note"
    crm_record = "crm_record"
    fetched_page = "fetched_page"


class EvidenceStatus(enum.StrEnum):
    accepted = "accepted"
    # Looks like instructions rather than facts. Kept out of scoring and models until reviewed.
    quarantined = "quarantined"
    rejected = "rejected"


class FitLabel(enum.StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class EvaluationStatus(enum.StrEnum):
    pending_review = "pending_review"
    insufficient_evidence = "insufficient_evidence"
    approved = "approved"
    rejected = "rejected"


class BriefStatus(enum.StrEnum):
    running = "running"
    completed = "completed"
    # The model answered, but no claim survived the output gate.
    rejected = "rejected"
    failed = "failed"


class IcpConfiguration(IdMixin, Base):
    """One immutable version. The newest version for an organization is the active one."""

    __tablename__ = "icp_configurations"
    __table_args__ = (UniqueConstraint("organization_id", "version"),)

    organization_id: Mapped[uuid.UUID] = _org_fk()
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    criteria: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    created_at: Mapped[datetime] = _created_at()


class ResearchEvidence(IdMixin, Base):
    __tablename__ = "research_evidence"
    __table_args__ = (
        # Adding the same text from the same kind of source twice is a no-op.
        UniqueConstraint("organization_id", "lead_id", "source_type", "content_hash"),
        Index("ix_research_evidence_lead", "lead_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    lead_id: Mapped[uuid.UUID] = _lead_fk()
    source_type: Mapped[EvidenceSource] = mapped_column(
        _enum(EvidenceSource, "evidence_source"), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(2048))
    title: Mapped[str | None] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[EvidenceStatus] = mapped_column(
        _enum(EvidenceStatus, "evidence_status"), nullable=False
    )
    # Names of the input-gate rules this text matched; empty when it matched none.
    screen_flags: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, default=list, server_default="{}"
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    reviewed_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class LeadAssessment(IdMixin, Base):
    """One scored result. New assessments are added; earlier ones stay as history."""

    __tablename__ = "lead_scores"
    __table_args__ = (
        Index("ix_lead_scores_lead", "lead_id", "created_at"),
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    lead_id: Mapped[uuid.UUID] = _lead_fk()
    icp_configuration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("icp_configurations.id", ondelete="RESTRICT"), nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    fit: Mapped[FitLabel] = mapped_column(_enum(FitLabel, "fit_label"), nullable=False)
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    positive_signals: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    negative_signals: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    missing_information: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    evidence_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    evaluation_status: Mapped[EvaluationStatus] = mapped_column(
        _enum(EvaluationStatus, "evaluation_status"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    reviewed_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class ResearchBrief(IdMixin, Base):
    """A model-written brief. Claims here are inference and never change a score."""

    __tablename__ = "research_briefs"
    __table_args__ = (
        Index("ix_research_briefs_lead", "lead_id", "created_at"),
        # At most one brief in progress per lead, so repeat clicks cannot queue up model calls.
        Index(
            "uq_research_briefs_running",
            "organization_id",
            "lead_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    lead_id: Mapped[uuid.UUID] = _lead_fk()
    status: Mapped[BriefStatus] = mapped_column(_enum(BriefStatus, "brief_status"), nullable=False)
    model_key: Mapped[str] = mapped_column(String(80), nullable=False)
    served_by: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    claims: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    rejected_claims: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    missing_information: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    evidence_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    failure_category: Mapped[str | None] = mapped_column(String(40))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_by_user_id: Mapped[uuid.UUID | None] = _user_fk()
    created_at: Mapped[datetime] = _created_at()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
