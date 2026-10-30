"""Agent, tool, and MCP token schemas."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import AgentRole, AgentStatus, TokenScope, ToolCallStatus


class AgentStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: uuid.UUID | None = None


class AgentInfo(BaseModel):
    role: AgentRole
    label: str
    description: str
    tools: list[str]
    needs_lead: bool
    max_model_turns: int
    max_tool_calls: int


class ToolInfo(BaseModel):
    name: str
    description: str
    side_effect: str
    permission: str


class CatalogOut(BaseModel):
    agents: list[AgentInfo]
    tools: list[ToolInfo]


class CitedClaim(BaseModel):
    text: str
    evidence_ids: list[str]


class RejectedAgentClaim(BaseModel):
    text: str | None
    problems: list[str]


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workflow_run_id: uuid.UUID
    lead_id: uuid.UUID | None
    role: AgentRole
    status: AgentStatus
    model_key: str
    stop_reason: str | None
    summary: str | None
    claims: list[CitedClaim]
    rejected_claims: list[RejectedAgentClaim]
    missing_information: list[str]
    review_notes: list[str]
    model_turns: int
    tool_call_count: int
    input_tokens: int | None
    output_tokens: int | None
    failure_category: str | None
    created_at: datetime
    completed_at: datetime | None


class ToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tool: str
    side_effect: str
    status: ToolCallStatus
    arguments: dict[str, str]
    error_category: str | None
    duration_ms: int | None
    created_at: datetime


class AgentRunDetail(AgentRunOut):
    tool_calls: list[ToolCallOut]
    sources: dict[str, str]


class TokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    scope: TokenScope = TokenScope.read
    expires_in_days: int = Field(default=30, ge=1, le=90)
    # Required for a write token. Never stored or logged.
    current_password: str | None = Field(default=None, max_length=256)


class TokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    scope: TokenScope
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class TokenCreated(TokenOut):
    """The only response that ever contains the secret."""

    secret: str
