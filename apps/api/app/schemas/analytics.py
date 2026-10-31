"""Analytics schemas. Every figure is counted from stored records when it is asked for."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class DayCount(BaseModel):
    day: date
    count: int


class LeadStats(BaseModel):
    added_by_day: list[DayCount]
    by_status: dict[str, int]
    # The latest assessment of each lead. "unscored" counts leads without one.
    by_fit: dict[str, int]
    assessments_awaiting_review: int


class OutreachStats(BaseModel):
    drafts_by_status: dict[str, int]
    # Attempts in the window. "accepted" means a mail server took it, not that it arrived.
    deliveries_by_status: dict[str, int]
    accepted_by_day: list[DayCount]
    suppressions_by_reason: dict[str, int]


class ApprovalStats(BaseModel):
    waiting: int
    approved: int
    rejected: int
    # None until something has been decided in the window.
    median_wait_hours: float | None


class PipelineStats(BaseModel):
    opened: int
    won: int
    lost: int
    # None until something has closed in the window. Counts, across currencies.
    win_rate: float | None
    won_value: dict[str, Decimal]


class FailureCount(BaseModel):
    category: str
    count: int


class WorkflowStats(BaseModel):
    by_status: dict[str, int]
    failures: list[FailureCount]
    median_minutes: float | None
    agent_runs_by_status: dict[str, int]
    tool_calls: int
    tool_calls_refused: int


class AnalyticsReport(BaseModel):
    days: int
    generated_at: datetime
    leads: LeadStats
    outreach: OutreachStats
    approvals: ApprovalStats
    pipeline: PipelineStats
    workflows: WorkflowStats


class Attention(BaseModel):
    """What is waiting on a person right now."""

    approvals_waiting: int
    drafts_ready_to_send: int
    outcomes_unknown: int
    workflows_waiting: int
    workflows_failed_7d: int
