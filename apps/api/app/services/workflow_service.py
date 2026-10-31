"""Start, read, cancel, resume, and decide on workflow runs. Tenant-scoped through OrgContext."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import OrgContext
from app.core.errors import ConflictError, NotFoundError
from app.core.rate_limit import RateLimitedError
from app.models import (
    BriefStatus,
    Lead,
    ResearchBrief,
    UsageKind,
    WorkflowKind,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStep,
)
from app.schemas.workflow import WorkflowStart
from app.services import audit, quota_service
from app.services.lead_service import get_lead

MAX_ACTIVE_PER_ORG = 20
RUN_TIME_LIMIT = timedelta(minutes=15)
_ACTIVE = (WorkflowStatus.queued, WorkflowStatus.running, WorkflowStatus.waiting_approval)


def _now() -> datetime:
    return datetime.now(UTC)


def enqueue(
    db: Session,
    ctx: OrgContext,
    lead_id: uuid.UUID | None,
    kind: WorkflowKind,
    *,
    urls: list[str] | None = None,
    propose_status: bool = False,
    role: str | None = None,
) -> WorkflowRun:
    if lead_id is not None:
        get_lead(db, ctx, lead_id)
    quota_service.check(db, ctx.org_id, "monthly_workflow_runs")
    quota_service.check_budget(db, ctx.org_id)
    active = db.scalar(
        select(func.count())
        .select_from(WorkflowRun)
        .where(WorkflowRun.organization_id == ctx.org_id, WorkflowRun.status.in_(_ACTIVE))
    )
    if (active or 0) >= MAX_ACTIVE_PER_ORG:
        raise RateLimitedError("Too many workflows are waiting. Try again shortly.")
    run = WorkflowRun(
        organization_id=ctx.org_id,
        lead_id=lead_id,
        kind=kind,
        status=WorkflowStatus.queued,
        input={"urls": urls or [], "propose_status": propose_status, "role": role},
        deadline_at=_now() + RUN_TIME_LIMIT,
        created_by_user_id=ctx.user_id,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError as exc:
        what = "this lead" if lead_id else "this agent"
        raise ConflictError(f"A workflow is already active for {what}") from exc
    quota_service.record(db, ctx.org_id, UsageKind.workflow_run, 1, workflow_run_id=run.id)
    audit.record(
        db,
        "workflow.started",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="workflow_run",
        target_id=run.id,
        data={"kind": kind.value, "lead_id": str(lead_id) if lead_id else None, "role": role},
    )
    return run


def start(db: Session, ctx: OrgContext, lead_id: uuid.UUID, body: WorkflowStart) -> WorkflowRun:
    return enqueue(
        db,
        ctx,
        lead_id,
        WorkflowKind.lead_intelligence,
        urls=body.urls,
        propose_status=body.propose_status,
    )


def list_runs(
    db: Session, ctx: OrgContext, *, lead_id: uuid.UUID | None = None, limit: int = 50
) -> list[WorkflowRun]:
    # A run's result goes with its lead, like the lead's other records.
    query = (
        select(WorkflowRun)
        .outerjoin(Lead, Lead.id == WorkflowRun.lead_id)
        .where(
            WorkflowRun.organization_id == ctx.org_id,
            WorkflowRun.lead_id.is_(None) | Lead.deleted_at.is_(None),
        )
    )
    if lead_id:
        query = query.where(WorkflowRun.lead_id == lead_id)
    return list(db.scalars(query.order_by(WorkflowRun.created_at.desc()).limit(limit)))


def get_run(db: Session, ctx: OrgContext, run_id: uuid.UUID) -> WorkflowRun:
    run = db.scalar(
        select(WorkflowRun)
        .outerjoin(Lead, Lead.id == WorkflowRun.lead_id)
        .where(
            WorkflowRun.id == run_id,
            WorkflowRun.organization_id == ctx.org_id,
            WorkflowRun.lead_id.is_(None) | Lead.deleted_at.is_(None),
        )
    )
    if run is None:
        raise NotFoundError("Workflow not found")
    return run


def list_steps(db: Session, ctx: OrgContext, run_id: uuid.UUID) -> list[WorkflowStep]:
    return list(
        db.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.organization_id == ctx.org_id, WorkflowStep.run_id == run_id)
            .order_by(WorkflowStep.started_at, WorkflowStep.id)
            .limit(200)
        )
    )


def _locked(db: Session, ctx: OrgContext, run_id: uuid.UUID) -> WorkflowRun:
    run = db.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.id == run_id, WorkflowRun.organization_id == ctx.org_id)
        .with_for_update()
    )
    if run is None:
        raise NotFoundError("Workflow not found")
    return run


def _record(db: Session, ctx: OrgContext, run: WorkflowRun, action: str, **data: object) -> None:
    audit.record(
        db,
        f"workflow.{action}",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="workflow_run",
        target_id=run.id,
        data=dict(data),
    )


def cancel(db: Session, ctx: OrgContext, run_id: uuid.UUID) -> WorkflowRun:
    """A waiting run stops now. A running one stops before its next step: a model call already
    under way finishes first, because it cannot be interrupted."""
    run = _locked(db, ctx, run_id)
    if run.status not in _ACTIVE:
        raise ConflictError("This workflow has already finished")
    run.cancel_requested_at = _now()
    if run.status != WorkflowStatus.running:
        run.status = WorkflowStatus.cancelled
        run.finished_at = _now()
        # No worker will see this run again, so its brief has to end here too.
        db.execute(
            update(ResearchBrief)
            .where(
                ResearchBrief.workflow_run_id == run.id,
                ResearchBrief.status == BriefStatus.running,
            )
            .values(status=BriefStatus.failed, failure_category="cancelled", completed_at=_now())
        )
    _record(db, ctx, run, "cancel_requested")
    return run


def resume(db: Session, ctx: OrgContext, run_id: uuid.UUID) -> WorkflowRun:
    """Queue a failed run again. It continues from its last checkpoint, not from the start."""
    run = _locked(db, ctx, run_id)
    if run.status != WorkflowStatus.failed:
        raise ConflictError("Only a failed workflow can be resumed")
    if run.error_category == "access_lost":
        raise ConflictError("The person who started this run no longer has access")
    quota_service.check_budget(db, ctx.org_id)
    run.status = WorkflowStatus.queued
    run.attempts = 0
    run.error_category = None
    run.error_message = None
    run.finished_at = None
    run.cancel_requested_at = None
    run.deadline_at = _now() + RUN_TIME_LIMIT
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("Another workflow is already active for this lead") from exc
    _record(db, ctx, run, "resumed")
    return run


def decide(db: Session, ctx: OrgContext, run_id: uuid.UUID, decision: str) -> WorkflowRun:
    run = _locked(db, ctx, run_id)
    if run.status != WorkflowStatus.waiting_approval:
        raise ConflictError("This workflow is not waiting for a decision")
    run.approval_decision = {
        "decision": decision,
        "by": str(ctx.user_id),
        "at": _now().isoformat(),
    }
    run.status = WorkflowStatus.queued
    run.attempts = 0  # Waiting for a person used none of the run's chances to survive a crash.
    run.deadline_at = _now() + RUN_TIME_LIMIT
    _record(db, ctx, run, "decided", decision=decision, request=run.approval_request)
    return run
