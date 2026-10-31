"""Counts from stored records, at request time. Nothing is estimated, sampled, or forecast.

A deleted lead leaves the counts about leads and drafts. Emails sent and runs that happened stay,
because they did happen. Days are UTC, like every other date in the product.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from app.core.auth import OrgContext
from app.models import (
    AgentRun,
    ApprovalRequest,
    ApprovalStatus,
    ConnectionHealth,
    Delivery,
    DeliveryStatus,
    DraftStatus,
    EvaluationStatus,
    IntegrationConnection,
    Lead,
    LeadAssessment,
    Opportunity,
    OutreachDraft,
    PipelineStage,
    StageKind,
    SuppressionEntry,
    ToolCall,
    ToolCallStatus,
    WorkflowRun,
    WorkflowStatus,
)
from app.schemas.analytics import (
    AnalyticsReport,
    ApprovalStats,
    Attention,
    DayCount,
    FailureCount,
    LeadStats,
    OutreachStats,
    PipelineStats,
    WorkflowStats,
)
from app.services.lead_service import latest_assessments


def _counts(db: Session, query: Any) -> dict[str, int]:
    """For a query selecting (key, count). Enum keys become their values."""
    return {getattr(key, "value", str(key)): count for key, count in db.execute(query).all()}


def _by_day(db: Session, column: Any, query: Any, since: datetime, days: int) -> list[DayCount]:
    """Every day in the window, including the empty ones, so a chart's axis tells the truth."""
    day = func.date(func.timezone("UTC", column))
    found: dict[date, int] = {
        row[0]: row[1]
        for row in db.execute(query.add_columns(day, func.count()).group_by(day)).all()
    }
    first = since.date()
    return [
        DayCount(day=first + timedelta(days=i), count=found.get(first + timedelta(days=i), 0))
        for i in range(days)
    ]


def _median(db: Session, seconds: Any, query: Any) -> float | None:
    value = db.scalar(query.add_columns(func.percentile_cont(0.5).within_group(seconds)))
    return float(value) if value is not None else None


def _leads(db: Session, ctx: OrgContext, since: datetime, days: int) -> LeadStats:
    live = (Lead.organization_id == ctx.org_id, Lead.deleted_at.is_(None))
    latest = latest_assessments()
    fit = func.coalesce(cast(latest.c.fit, String), "unscored")
    by_fit = _counts(
        db,
        select(fit, func.count())
        .select_from(Lead)
        .outerjoin(latest, latest.c.lead_id == Lead.id)
        .where(*live)
        .group_by(fit),
    )
    return LeadStats(
        added_by_day=_by_day(
            db,
            Lead.created_at,
            select().select_from(Lead).where(*live, Lead.created_at >= since),
            since,
            days,
        ),
        by_status=_counts(db, select(Lead.status, func.count()).where(*live).group_by(Lead.status)),
        by_fit=by_fit,
        assessments_awaiting_review=db.scalar(
            select(func.count())
            .select_from(LeadAssessment)
            .join(Lead, Lead.id == LeadAssessment.lead_id)
            .where(*live, LeadAssessment.evaluation_status == EvaluationStatus.pending_review)
        )
        or 0,
    )


def _outreach(db: Session, ctx: OrgContext, since: datetime, days: int) -> OutreachStats:
    org = Delivery.organization_id == ctx.org_id
    return OutreachStats(
        drafts_by_status=_counts(
            db,
            select(OutreachDraft.status, func.count())
            .join(Lead, Lead.id == OutreachDraft.lead_id)
            .where(OutreachDraft.organization_id == ctx.org_id, Lead.deleted_at.is_(None))
            .group_by(OutreachDraft.status),
        ),
        deliveries_by_status=_counts(
            db,
            select(Delivery.status, func.count())
            .where(org, Delivery.created_at >= since)
            .group_by(Delivery.status),
        ),
        accepted_by_day=_by_day(
            db,
            Delivery.created_at,
            select()
            .select_from(Delivery)
            .where(org, Delivery.created_at >= since, Delivery.status == DeliveryStatus.accepted),
            since,
            days,
        ),
        suppressions_by_reason=_counts(
            db,
            select(SuppressionEntry.reason, func.count())
            .where(
                SuppressionEntry.organization_id == ctx.org_id,
                SuppressionEntry.removed_at.is_(None),
            )
            .group_by(SuppressionEntry.reason),
        ),
    )


def _approvals(db: Session, ctx: OrgContext, since: datetime) -> ApprovalStats:
    org = ApprovalRequest.organization_id == ctx.org_id
    decided = _counts(
        db,
        select(ApprovalRequest.status, func.count())
        .where(org, ApprovalRequest.decided_at >= since)
        .group_by(ApprovalRequest.status),
    )
    wait = func.extract("epoch", ApprovalRequest.decided_at - ApprovalRequest.created_at)
    median = _median(
        db,
        wait,
        select().select_from(ApprovalRequest).where(org, ApprovalRequest.decided_at >= since),
    )
    return ApprovalStats(
        waiting=_waiting_approvals(db, ctx),
        approved=decided.get(ApprovalStatus.approved.value, 0),
        rejected=decided.get(ApprovalStatus.rejected.value, 0),
        median_wait_hours=round(median / 3600, 1) if median is not None else None,
    )


def _pipeline(db: Session, ctx: OrgContext, since: datetime) -> PipelineStats:
    org = Opportunity.organization_id == ctx.org_id
    closed = (
        select(PipelineStage.kind, func.count())
        .join(Opportunity, Opportunity.stage_id == PipelineStage.id)
        .where(org, Opportunity.closed_at >= since)
        .group_by(PipelineStage.kind)
    )
    counts = _counts(db, closed)
    won, lost = counts.get(StageKind.won.value, 0), counts.get(StageKind.lost.value, 0)
    values = db.execute(
        select(Opportunity.currency, func.sum(Opportunity.amount))
        .join(PipelineStage, PipelineStage.id == Opportunity.stage_id)
        .where(
            org,
            Opportunity.closed_at >= since,
            PipelineStage.kind == StageKind.won,
            Opportunity.amount.is_not(None),
        )
        .group_by(Opportunity.currency)
    ).all()
    return PipelineStats(
        opened=db.scalar(
            select(func.count())
            .select_from(Opportunity)
            .where(org, Opportunity.created_at >= since)
        )
        or 0,
        won=won,
        lost=lost,
        win_rate=round(won / (won + lost), 3) if won + lost else None,
        won_value={currency: total for currency, total in values if total is not None},
    )


def _workflows(db: Session, ctx: OrgContext, since: datetime) -> WorkflowStats:
    org = WorkflowRun.organization_id == ctx.org_id
    recent = WorkflowRun.created_at >= since
    category = func.coalesce(WorkflowRun.error_category, "unknown")
    failures = db.execute(
        select(category, func.count())
        .where(org, recent, WorkflowRun.status == WorkflowStatus.failed)
        .group_by(category)
        .order_by(func.count().desc())
        .limit(8)
    ).all()
    took = func.extract("epoch", WorkflowRun.finished_at - WorkflowRun.created_at)
    median = _median(
        db,
        took,
        select()
        .select_from(WorkflowRun)
        .where(org, recent, WorkflowRun.status == WorkflowStatus.succeeded),
    )
    calls = _counts(
        db,
        select(ToolCall.status, func.count())
        .where(ToolCall.organization_id == ctx.org_id, ToolCall.created_at >= since)
        .group_by(ToolCall.status),
    )
    return WorkflowStats(
        by_status=_counts(
            db,
            select(WorkflowRun.status, func.count())
            .where(org, recent)
            .group_by(WorkflowRun.status),
        ),
        failures=[FailureCount(category=c, count=n) for c, n in failures],
        median_minutes=round(median / 60, 1) if median is not None else None,
        agent_runs_by_status=_counts(
            db,
            select(AgentRun.status, func.count())
            .where(AgentRun.organization_id == ctx.org_id, AgentRun.created_at >= since)
            .group_by(AgentRun.status),
        ),
        tool_calls=sum(calls.values()),
        tool_calls_refused=calls.get(ToolCallStatus.denied.value, 0),
    )


def report(db: Session, ctx: OrgContext, days: int) -> AnalyticsReport:
    now = datetime.now(UTC)
    # The whole of the first day, so that the first bar is not a partial one.
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return AnalyticsReport(
        days=days,
        generated_at=now,
        leads=_leads(db, ctx, since, days),
        outreach=_outreach(db, ctx, since, days),
        approvals=_approvals(db, ctx, since),
        pipeline=_pipeline(db, ctx, since),
        workflows=_workflows(db, ctx, since),
    )


def _waiting_approvals(db: Session, ctx: OrgContext) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(ApprovalRequest)
            .join(OutreachDraft, OutreachDraft.id == ApprovalRequest.draft_id)
            .join(Lead, Lead.id == OutreachDraft.lead_id)
            .where(
                ApprovalRequest.organization_id == ctx.org_id,
                ApprovalRequest.status == ApprovalStatus.pending,
                ApprovalRequest.expires_at > datetime.now(UTC),
                Lead.deleted_at.is_(None),
            )
        )
        or 0
    )


def attention(db: Session, ctx: OrgContext) -> Attention:
    drafts = _counts(
        db,
        select(OutreachDraft.status, func.count())
        .join(Lead, Lead.id == OutreachDraft.lead_id)
        .where(
            OutreachDraft.organization_id == ctx.org_id,
            Lead.deleted_at.is_(None),
            OutreachDraft.status.in_((DraftStatus.approved, DraftStatus.send_unknown)),
        )
        .group_by(OutreachDraft.status),
    )
    runs = WorkflowRun.organization_id == ctx.org_id
    return Attention(
        approvals_waiting=_waiting_approvals(db, ctx),
        drafts_ready_to_send=drafts.get(DraftStatus.approved.value, 0),
        outcomes_unknown=drafts.get(DraftStatus.send_unknown.value, 0),
        workflows_waiting=db.scalar(
            select(func.count())
            .select_from(WorkflowRun)
            .where(runs, WorkflowRun.status == WorkflowStatus.waiting_approval)
        )
        or 0,
        integrations_failing=db.scalar(
            select(func.count())
            .select_from(IntegrationConnection)
            .where(
                IntegrationConnection.organization_id == ctx.org_id,
                IntegrationConnection.removed_at.is_(None),
                IntegrationConnection.health == ConnectionHealth.failing,
            )
        )
        or 0,
        workflows_failed_7d=db.scalar(
            select(func.count())
            .select_from(WorkflowRun)
            .where(
                runs,
                WorkflowRun.status == WorkflowStatus.failed,
                WorkflowRun.created_at >= datetime.now(UTC) - timedelta(days=7),
            )
        )
        or 0,
    )
