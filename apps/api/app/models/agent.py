"""Agent runs, the audit log of tool calls, and access tokens for the MCP server."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


def _org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )


class AgentRole(enum.StrEnum):
    research = "research"
    qualification = "qualification"
    pipeline = "pipeline"


class AgentStatus(enum.StrEnum):
    running = "running"
    completed = "completed"
    # The agent answered, but none of its claims passed the review.
    rejected = "rejected"
    failed = "failed"


class ToolCallStatus(enum.StrEnum):
    ok = "ok"
    denied = "denied"
    invalid = "invalid"
    error = "error"


class TokenScope(enum.StrEnum):
    read = "read"
    write = "write"


class AgentRun(IdMixin, Base):
    """What one agent concluded. Its claims are inference, and nothing reads them to act."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_org_created", "organization_id", "created_at"),
        Index("ix_agent_runs_lead", "lead_id"),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE")
    )
    role: Mapped[AgentRole] = mapped_column(_enum(AgentRole, "agent_role"), nullable=False)
    status: Mapped[AgentStatus] = mapped_column(_enum(AgentStatus, "agent_status"), nullable=False)
    model_key: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    stop_reason: Mapped[str | None] = mapped_column(String(40))
    summary: Mapped[str | None] = mapped_column(Text)
    claims: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    rejected_claims: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    missing_information: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    review_notes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    sources: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    model_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    failure_category: Mapped[str | None] = mapped_column(String(40))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ToolCall(IdMixin, Base):
    """Append-only record of every tool call, including the ones that were refused."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        Index("ix_tool_calls_org_created", "organization_id", "created_at"),
        Index("ix_tool_calls_run", "workflow_run_id"),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="SET NULL")
    )
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_tokens.id", ondelete="SET NULL")
    )
    tool: Mapped[str] = mapped_column(String(80), nullable=False)
    side_effect: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[ToolCallStatus] = mapped_column(
        _enum(ToolCallStatus, "tool_call_status"), nullable=False
    )
    # Only fields a tool marks as safe to keep, such as IDs. Never free text.
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_category: Mapped[str | None] = mapped_column(String(40))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class McpToken(IdMixin, Base):
    """A personal token for an MCP client. Only its digest is stored. It can never do more than
    its owner's current role allows, and a read token can only use read-only tools."""

    __tablename__ = "mcp_tokens"
    __table_args__ = (Index("ix_mcp_tokens_user", "user_id"),)

    organization_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scope: Mapped[TokenScope] = mapped_column(_enum(TokenScope, "mcp_token_scope"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
