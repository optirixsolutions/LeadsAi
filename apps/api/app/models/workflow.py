"""Durable workflow runs and their step-by-step trace.

These are the long-term records. LangGraph's checkpoints live apart in the `workflow_state`
schema, hold only IDs and statuses, and are deleted when a run finishes.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class WorkflowKind(enum.StrEnum):
    research = "research"
    lead_intelligence = "lead_intelligence"
    agent = "agent"


class WorkflowStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    waiting_approval = "waiting_approval"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class StepStatus(enum.StrEnum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    # The worker died during this step. A later attempt repeats it.
    interrupted = "interrupted"
    waiting = "waiting"


class WorkflowRun(IdMixin, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_lead", "lead_id", "created_at"),
        Index("ix_workflow_runs_org_created", "organization_id", "created_at"),
        Index("ix_workflow_runs_claim", "status", "created_at"),
        # The same for work about the whole organization: one active run of each agent.
        Index(
            "uq_workflow_runs_active_org_role",
            "organization_id",
            text("(input->>'role')"),
            unique=True,
            postgresql_where=text(
                "lead_id IS NULL AND status IN ('queued', 'running', 'waiting_approval')"
            ),
        ),
        # One active run per lead, so repeat clicks and retries cannot stack up.
        Index(
            "uq_workflow_runs_active_lead",
            "organization_id",
            "lead_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running', 'waiting_approval')"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Empty for work about the whole organization, such as the pipeline analyst.
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE")
    )
    kind: Mapped[WorkflowKind] = mapped_column(_enum(WorkflowKind, "workflow_kind"), nullable=False)
    status: Mapped[WorkflowStatus] = mapped_column(
        _enum(WorkflowStatus, "workflow_status"), nullable=False
    )
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    current_step: Mapped[str | None] = mapped_column(String(60))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    lease_owner: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_category: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(500))
    approval_request: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    approval_decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowStep(IdMixin, Base):
    """One attempt at one graph node. A retried step adds a row, so the trace shows retries."""

    __tablename__ = "workflow_steps"
    __table_args__ = (Index("ix_workflow_steps_run", "run_id", "started_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[StepStatus] = mapped_column(_enum(StepStatus, "workflow_step_status"))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_category: Mapped[str | None] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
