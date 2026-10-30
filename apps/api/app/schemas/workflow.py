"""Workflow request and response schemas."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models import StepStatus, WorkflowKind, WorkflowStatus


class WorkflowStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Pages to fetch first. Each still goes through the fetcher's allowlist and IP checks.
    urls: list[Annotated[str, Field(max_length=2048)]] = Field(default=[], max_length=3)
    # Pause for a person's decision before changing the lead's status.
    propose_status: bool = False


class WorkflowDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]


class WorkflowRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    kind: WorkflowKind
    status: WorkflowStatus
    current_step: str | None
    attempts: int
    max_attempts: int
    cancel_requested_at: datetime | None
    error_category: str | None
    error_message: str | None
    approval_request: dict[str, Any] | None
    approval_decision: dict[str, Any] | None
    result: dict[str, Any] | None
    created_by_user_id: uuid.UUID
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resumable(self) -> bool:
        return self.status == WorkflowStatus.failed and self.error_category != "access_lost"


class WorkflowStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: StepStatus
    detail: dict[str, Any]
    error_category: str | None
    started_at: datetime
    finished_at: datetime | None


class WorkflowRunDetail(WorkflowRunOut):
    steps: list[WorkflowStepOut]


class WorkerHealthOut(BaseModel):
    alive: bool
