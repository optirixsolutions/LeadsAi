"""Graph nodes. Each records its own trace row, and each is safe to run twice.

A node can repeat after a crash, because the last checkpoint is from before it. Side effects
are protected: an assessment and a brief are unique per run, evidence is deduplicated by content,
and applying a status change checks the lead still has the status the approver saw.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.errors import GraphBubbleUp
from langgraph.types import interrupt
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agents.llm import LLMError
from app.core.auth import OrgContext, worker_context
from app.core.db import get_worker_sessionmaker, set_tenant_context
from app.core.errors import (
    AppError,
    LeaseLostError,
    RequestInvalidError,
    WorkflowStoppedError,
)
from app.core.permissions import Permission, has_permission
from app.integrations.fetcher import FetchBlockedError, FetchFailedError
from app.models import (
    ActivityType,
    AuditLog,
    BriefStatus,
    EvaluationStatus,
    EvidenceSource,
    EvidenceStatus,
    FitLabel,
    Lead,
    LeadAssessment,
    LeadStatus,
    ResearchEvidence,
    StepStatus,
    WorkflowRun,
    WorkflowStep,
)
from app.services import agent_service, audit, brief_service, intelligence_service
from app.services.lead_service import get_lead, record_activity
from app.workflows.state import WorkflowState

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _check_run(db: Session, state: WorkflowState, owner: str) -> None:
    run = db.get(WorkflowRun, uuid.UUID(state["run_id"]), populate_existing=True)
    if run is None or run.lease_owner != owner:
        raise WorkflowStoppedError("lease_lost")
    if run.cancel_requested_at is not None:
        raise WorkflowStoppedError("cancelled")
    if run.deadline_at < _now():
        raise WorkflowStoppedError("deadline")


NodeFn = Callable[[Session, OrgContext, WorkflowState], dict[str, Any]]


class StepFailedError(Exception):
    """Stands in for an unexpected error. LangGraph stores a node's exception in its checkpoint,
    outside row-level security, so the original text goes to the logs and not there."""


def _acting_user(db: Session, state: WorkflowState) -> uuid.UUID:
    """The requester, until someone decides on the run. From then on the decision is theirs, so
    the audit trail names them, and the requester leaving cannot stop what they approved."""
    org_id, requester = uuid.UUID(state["org_id"]), uuid.UUID(state["actor_id"])
    set_tenant_context(db, user_id=requester, org_id=org_id)
    decision = db.scalar(
        select(WorkflowRun.approval_decision).where(WorkflowRun.id == uuid.UUID(state["run_id"]))
    )
    return uuid.UUID(decision["by"]) if decision else requester


def traced(name: str, fn: NodeFn, owner: str) -> Any:
    """Run a node in its own session, with its work and its trace row committed together."""

    def node(state: WorkflowState) -> dict[str, Any]:
        run_id = uuid.UUID(state["run_id"])
        org_id = uuid.UUID(state["org_id"])
        with get_worker_sessionmaker()() as db:
            ctx = worker_context(db, org_id, _acting_user(db, state))
            # Checked at every step: a role can change while a run waits or is resumed later.
            if not has_permission(ctx.role, Permission.workflows_run):
                raise RequestInvalidError(
                    "The person acting on this run can no longer run workflows"
                )
            _check_run(db, state, owner)
            step = WorkflowStep(
                organization_id=org_id, run_id=run_id, name=name, status=StepStatus.running
            )
            db.add(step)
            db.execute(
                update(WorkflowRun).where(WorkflowRun.id == run_id).values(current_step=name)
            )
            db.commit()
            step_id = step.id
            set_tenant_context(db, user_id=ctx.user_id, org_id=org_id)
            try:
                output = fn(db, ctx, state)
            except GraphBubbleUp:
                db.rollback()
                _close_step(db, ctx, step_id, StepStatus.waiting)
                raise
            except (WorkflowStoppedError, LeaseLostError):
                db.rollback()
                _close_step(db, ctx, step_id, StepStatus.interrupted)
                raise
            except Exception as exc:
                db.rollback()
                raise _failed(db, ctx, step_id, name, exc) from None
            trace = output.pop("trace", {})
            set_tenant_context(db, user_id=ctx.user_id, org_id=org_id)
            db.execute(
                update(WorkflowStep)
                .where(WorkflowStep.id == step_id)
                .values(
                    status=StepStatus.succeeded,
                    finished_at=_now(),
                    detail={**_trace_detail(output), **trace},
                )
            )
            db.commit()
            return output

    return node


def _failed(
    db: Session, ctx: OrgContext, step_id: uuid.UUID, name: str, exc: Exception
) -> Exception:
    """Record a failed step and return an exception that is safe to checkpoint."""
    log.warning(
        "workflow_step_failed",
        extra={"step": name, "error_type": type(exc).__name__, "detail": str(exc)[:300]},
    )
    if isinstance(exc, LLMError):
        detail = {"attempts": exc.details.get("attempts")}
        _close_step(db, ctx, step_id, StepStatus.failed, category=exc.category[:40], detail=detail)
        # Provider responses can quote hostnames and internal detail.
        exc.message = exc.category
        exc.details = {}
        return exc
    _close_step(db, ctx, step_id, StepStatus.failed, category=type(exc).__name__[:40])
    return exc if isinstance(exc, AppError) else StepFailedError(type(exc).__name__)


def _close_step(
    db: Session,
    ctx: OrgContext,
    step_id: uuid.UUID,
    status: StepStatus,
    *,
    category: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    set_tenant_context(db, user_id=ctx.user_id, org_id=ctx.org_id)
    db.execute(
        update(WorkflowStep)
        .where(WorkflowStep.id == step_id)
        .values(status=status, error_category=category, finished_at=_now(), detail=detail or {})
    )
    db.commit()


def _trace_detail(output: dict[str, Any]) -> dict[str, Any]:
    """What a person needs to follow the run. IDs and counts, never long lists of text."""
    return {
        k: (len(v) if k == "evidence_ids" else v)
        for k, v in output.items()
        if k not in ("usage", "proposal")
    }


# --- nodes ------------------------------------------------------------------------------


def validate_request(db: Session, ctx: OrgContext, state: WorkflowState) -> dict[str, Any]:
    if state.get("lead_id"):
        get_lead(db, ctx, uuid.UUID(str(state["lead_id"])))
    return {}


def load_context(db: Session, ctx: OrgContext, state: WorkflowState) -> dict[str, Any]:
    icp = intelligence_service.active_icp(db, ctx)
    if icp is None:
        raise RequestInvalidError("Set up the ideal customer profile before running this workflow")
    return {"icp_version": icp.version}


def gather_evidence(db: Session, ctx: OrgContext, state: WorkflowState) -> dict[str, Any]:
    """Fetch the pages the person asked for. One bad page is noted and does not stop the run."""
    run = db.get(WorkflowRun, uuid.UUID(state["run_id"]))
    urls: list[str] = (run.input if run else {}).get("urls", [])
    problems: list[str] = []
    for url in urls:
        try:
            intelligence_service.fetch_evidence(db, ctx, uuid.UUID(str(state["lead_id"])), url)
            db.commit()
            set_tenant_context(db, user_id=ctx.user_id, org_id=ctx.org_id)
        except (FetchBlockedError, FetchFailedError) as exc:
            db.rollback()
            set_tenant_context(db, user_id=ctx.user_id, org_id=ctx.org_id)
            problems.append(f"{url[:200]}: {exc.message}")
        except AppError as exc:
            db.rollback()
            set_tenant_context(db, user_id=ctx.user_id, org_id=ctx.org_id)
            problems.append(exc.message)
            break
    # The addresses stay in the trace, under row-level security. The checkpoint gets a count.
    return {"fetch_problem_count": len(problems), "trace": {"fetch_problems": problems}}


def validate_sources(db: Session, ctx: OrgContext, state: WorkflowState) -> dict[str, Any]:
    rows = db.execute(
        select(ResearchEvidence.id, ResearchEvidence.status, ResearchEvidence.source_type).where(
            ResearchEvidence.organization_id == ctx.org_id,
            ResearchEvidence.lead_id == uuid.UUID(str(state["lead_id"])),
        )
    ).all()
    usable = [
        str(r.id)
        for r in rows
        if r.status == EvidenceStatus.accepted and r.source_type != EvidenceSource.crm_record
    ]
    return {
        "evidence_ids": usable,
        "quarantined_count": sum(r.status == EvidenceStatus.quarantined for r in rows),
    }


def score_lead(db: Session, ctx: OrgContext, state: WorkflowState) -> dict[str, Any]:
    assessment = intelligence_service.assess_lead(
        db, ctx, uuid.UUID(str(state["lead_id"])), workflow_run_id=uuid.UUID(state["run_id"])
    )
    return {
        "assessment_id": str(assessment.id),
        "score": assessment.score,
        "fit": assessment.fit.value,
        "evaluation_status": assessment.evaluation_status.value,
    }


def interpret(owner: str) -> NodeFn:
    """Model-written brief, through the output gate. Its result never reaches the score."""

    def run(db: Session, ctx: OrgContext, state: WorkflowState) -> dict[str, Any]:
        outcome = brief_service.write_brief(
            db, ctx, uuid.UUID(str(state["lead_id"])), uuid.UUID(state["run_id"]), owner=owner
        )
        return {
            "brief_id": str(outcome.brief_id),
            "brief_status": outcome.status.value,
            "brief_failure": outcome.failure,
            "usage": outcome.usage,
        }

    return run


def run_agent(owner: str) -> NodeFn:
    """A bounded agent, whose answer the deterministic review checks before it is stored."""

    def run(db: Session, ctx: OrgContext, state: WorkflowState) -> dict[str, Any]:
        return agent_service.run_step(
            db,
            ctx,
            uuid.UUID(state["run_id"]),
            owner=owner,
            session_factory=get_worker_sessionmaker(),
        )

    return run


def quality_review(db: Session, ctx: OrgContext, state: WorkflowState) -> dict[str, Any]:
    """Accept or escalate, by fixed rules. Nothing here reads what the model wrote."""
    reasons: list[str] = []
    if state.get("evaluation_status") == EvaluationStatus.insufficient_evidence.value:
        reasons.append("No current research evidence behind the score")
    if state.get("quarantined_count"):
        reasons.append(f"{state['quarantined_count']} evidence item(s) await review")
    if state.get("fetch_problem_count"):
        reasons.append(f"{state['fetch_problem_count']} requested page(s) could not be used")
    if state.get("brief_status") == BriefStatus.rejected.value:
        reasons.append("No claim in the model's brief passed the evidence checks")
    if state.get("brief_status") == BriefStatus.failed.value:
        reasons.append("The model could not produce a usable brief")
    return {
        "decision": "escalated" if reasons else "accepted",
        "escalation_reasons": reasons,
        "proposal": _proposal(db, ctx, state, reasons),
    }


def _proposal(
    db: Session, ctx: OrgContext, state: WorkflowState, reasons: list[str]
) -> dict[str, Any] | None:
    run = db.get(WorkflowRun, uuid.UUID(state["run_id"]))
    if run is None or not run.input.get("propose_status") or reasons:
        return None
    target = {
        FitLabel.high.value: LeadStatus.qualified,
        FitLabel.low.value: LeadStatus.disqualified,
    }.get(state.get("fit") or "")
    lead = get_lead(db, ctx, uuid.UUID(str(state["lead_id"])))
    if target is None or lead.status == target:
        return None
    return {
        "action": "set_lead_status",
        "from": lead.status.value,
        "to": target.value,
        "score": state.get("score"),
        "fit": state.get("fit"),
        "assessment_id": state.get("assessment_id"),
    }


def request_approval(db: Session, ctx: OrgContext, state: WorkflowState) -> dict[str, Any]:
    """Pause until a person decides. The graph resumes here with their answer."""
    db.commit()
    decision = interrupt(state["proposal"])
    return {"approval": str(decision)}


def apply_decision(db: Session, ctx: OrgContext, state: WorkflowState) -> dict[str, Any]:
    """Runs as the person who decided, so the record names them, not the requester."""
    proposal = state.get("proposal") or {}
    approved = state.get("approval") == "approved"
    if not has_permission(ctx.role, Permission.intelligence_review):
        raise RequestInvalidError("The person who decided can no longer review assessments")
    lead = db.scalar(
        select(Lead)
        .where(Lead.id == uuid.UUID(str(state["lead_id"])), Lead.deleted_at.is_(None))
        .with_for_update()
    )
    if lead is None:
        return {"proposal_applied": False}
    assessment = db.get(LeadAssessment, uuid.UUID(str(proposal.get("assessment_id"))))
    if assessment is not None and assessment.reviewed_at is None:
        intelligence_service.review_assessment(
            db,
            ctx,
            assessment.id,
            EvaluationStatus.approved if approved else EvaluationStatus.rejected,
        )
    elif assessment is not None and assessment.evaluation_status == EvaluationStatus.rejected:
        # Someone rejected this assessment directly while the run waited. That stands.
        return {"proposal_applied": False}
    # The same goes for a person who moved the lead in the meantime.
    if not approved or lead.status.value != proposal.get("from"):
        return {"proposal_applied": False}
    lead.status = LeadStatus(str(proposal.get("to")))
    record_activity(
        db,
        ctx,
        ActivityType.status_changed,
        lead_id=lead.id,
        data={"from": proposal.get("from"), "to": proposal.get("to"), "via": "workflow"},
    )
    return {"proposal_applied": True}


def finalize(db: Session, ctx: OrgContext, state: WorkflowState) -> dict[str, Any]:
    already = db.scalar(
        select(AuditLog.id).where(
            AuditLog.action == "workflow.completed", AuditLog.target_id == state["run_id"]
        )
    )
    if already is not None:
        return {}  # This step ran before a crash; one audit entry is the right number.
    audit.record(
        db,
        "workflow.completed",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="workflow_run",
        target_id=state["run_id"],
        data={
            "decision": state.get("decision"),
            "assessment_id": state.get("assessment_id"),
            "brief_id": state.get("brief_id"),
            "approval": state.get("approval"),
        },
    )
    return {}
