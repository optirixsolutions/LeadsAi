"""Starts agent runs, runs them as workflow steps, and applies the deterministic review."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.agents.gates import EmailReview, check_email, check_output
from app.agents.llm import Usage
from app.agents.llm.registry import estimate_cost
from app.agents.roles import AGENT_PROMPT_VERSION, AGENTS
from app.agents.runtime import AgentResult, run_agent
from app.core.auth import OrgContext
from app.core.db import set_tenant_context
from app.core.errors import AppError, LeaseLostError, NotFoundError, WorkflowStoppedError
from app.mcp.registry import Identity
from app.models import (
    AgentRole,
    AgentRun,
    AgentStatus,
    Lead,
    TokenScope,
    ToolCall,
    UsageKind,
    WorkflowKind,
    WorkflowRun,
    WorkflowStatus,
)
from app.services import outreach_service, quota_service, workflow_service
from app.services.brief_service import get_registry
from app.services.lead_service import get_lead

_ENDED_RUNS = (WorkflowStatus.failed, WorkflowStatus.cancelled)


def _now() -> datetime:
    return datetime.now(UTC)


def start(db: Session, ctx: OrgContext, role: AgentRole, lead_id: uuid.UUID | None) -> AgentRun:
    definition = AGENTS[role]
    if definition.needs_lead and lead_id is None:
        raise AppError("This agent needs a lead", code="lead_required", details=None)
    if not definition.needs_lead:
        lead_id = None
    if definition.writes_email and lead_id is not None:
        outreach_service.require_contactable(db, ctx, lead_id)
    run = workflow_service.enqueue(db, ctx, lead_id, WorkflowKind.agent, role=role.value)
    agent = AgentRun(
        organization_id=ctx.org_id,
        workflow_run_id=run.id,
        lead_id=lead_id,
        role=role,
        status=AgentStatus.running,
        model_key=get_registry().routes[definition.route],
        prompt_version=AGENT_PROMPT_VERSION,
        created_by_user_id=ctx.user_id,
    )
    db.add(agent)
    db.flush()
    return agent


def _visible(ctx: OrgContext) -> Any:
    return (
        select(AgentRun)
        .outerjoin(Lead, Lead.id == AgentRun.lead_id)
        .where(
            AgentRun.organization_id == ctx.org_id,
            (AgentRun.lead_id.is_(None)) | (Lead.deleted_at.is_(None)),
        )
    )


def _settle(db: Session, agent: AgentRun) -> AgentRun:
    """A run can end with no worker left to tidy up, such as when it is cancelled in the queue."""
    if agent.status == AgentStatus.running:
        run = db.get(WorkflowRun, agent.workflow_run_id)
        if run is not None and run.status in _ENDED_RUNS:
            agent.status = AgentStatus.failed
            agent.failure_category = run.error_category or run.status.value
            agent.completed_at = _now()
    return agent


def list_runs(
    db: Session, ctx: OrgContext, *, lead_id: uuid.UUID | None = None, limit: int = 50
) -> list[AgentRun]:
    query = _visible(ctx)
    if lead_id:
        query = query.where(AgentRun.lead_id == lead_id)
    rows = db.scalars(query.order_by(AgentRun.created_at.desc()).limit(limit))
    return [_settle(db, a) for a in rows]


def get_run(db: Session, ctx: OrgContext, agent_id: uuid.UUID) -> AgentRun:
    agent = db.scalar(_visible(ctx).where(AgentRun.id == agent_id))
    if agent is None:
        raise NotFoundError("Agent run not found")
    return _settle(db, agent)


def tool_calls(db: Session, ctx: OrgContext, agent: AgentRun) -> list[ToolCall]:
    return list(
        db.scalars(
            select(ToolCall)
            .where(
                ToolCall.organization_id == ctx.org_id,
                ToolCall.workflow_run_id == agent.workflow_run_id,
            )
            .order_by(ToolCall.created_at)
            .limit(200)
        )
    )


def _task(definition: Any, lead_id: uuid.UUID | None) -> str:
    if lead_id is None:
        return "Summarize the current sales pipeline."
    return f"The lead's ID is {lead_id}. Do your job for this lead."


def review(result: AgentResult) -> tuple[Any, list[str]]:
    """The Quality and Policy Reviewer: fixed rules, nothing a model could talk its way past."""
    assert result.output is not None
    notes = []
    gated = check_output(result.output, result.sources)
    if result.stop_reason != "finished":
        notes.append(f"The agent stopped at a limit ({result.stop_reason})")
    if result.refused_calls:
        notes.append(f"{len(result.refused_calls)} tool call(s) were refused or invalid")
    if not result.sources:
        notes.append("The agent read no sources, so nothing it said can be checked")
    if gated.summary is None and result.output.summary:
        notes.append("The summary was removed because the sources do not support it")
    if len(gated.missing_information) < len(result.output.missing_information):
        notes.append("Some items listed as unknown were removed by the checks")
    return gated, notes


def run_step(
    db: Session,
    ctx: OrgContext,
    run_id: uuid.UUID,
    *,
    owner: str,
    session_factory: sessionmaker[Session],
) -> dict[str, Any]:
    """Workflow step. A finished result is returned as it is, so repeating this is harmless."""
    agent = db.scalar(select(AgentRun).where(AgentRun.workflow_run_id == run_id))
    if agent is None:
        raise AppError("This run has no agent", code="request_invalid")
    if agent.status in (AgentStatus.completed, AgentStatus.rejected):
        return {"agent_id": str(agent.id), "agent_status": agent.status.value}
    # The budget may have gone while this run waited in the queue.
    quota_service.check_budget(db, ctx.org_id)
    definition = AGENTS[agent.role]
    agent_id, lead_id, model_key = agent.id, agent.lead_id, agent.model_key
    agent.status = AgentStatus.running
    agent.failure_category = None
    if lead_id is not None:
        get_lead(db, ctx, lead_id)
    identity = Identity(
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        scope=TokenScope.read,
        workflow_run_id=run_id,
        allowed_tools=definition.tools,
        bound_lead_id=lead_id,
    )
    registry = get_registry()
    # An agent can run for minutes; do not hold a connection or locks across it.
    db.commit()

    def check() -> None:
        """Between model turns: has this run been cancelled, timed out, or taken over?"""
        with session_factory() as session:
            set_tenant_context(session, user_id=ctx.user_id, org_id=ctx.org_id)
            row = session.execute(
                select(
                    WorkflowRun.lease_owner,
                    WorkflowRun.cancel_requested_at,
                    WorkflowRun.deadline_at,
                ).where(WorkflowRun.id == run_id)
            ).first()
        if row is None or row.lease_owner != owner:
            raise LeaseLostError
        if row.cancel_requested_at is not None:
            raise WorkflowStoppedError("cancelled")
        if row.deadline_at < _now():
            raise WorkflowStoppedError("deadline")

    def record(status: AgentStatus, **values: Any) -> None:
        # Locked, so a takeover or a cancellation cannot slip in between the check and the write.
        set_tenant_context(db, user_id=ctx.user_id, org_id=ctx.org_id)
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update())
        if run is None or run.lease_owner != owner:
            db.rollback()
            raise LeaseLostError
        if run.cancel_requested_at is not None:
            db.rollback()
            raise WorkflowStoppedError("cancelled")
        db.execute(
            update(AgentRun)
            .where(AgentRun.id == agent_id)
            .values(status=status, completed_at=_now(), **values)
        )
        quota_service.record(
            db,
            ctx.org_id,
            UsageKind.model_tokens,
            result.input_tokens + result.output_tokens,
            model_key=result.served_by or model_key,
            estimated_cost_usd=estimate_cost(
                registry.model(result.served_by or model_key),
                Usage(result.input_tokens, result.output_tokens),
            ),
            workflow_run_id=run_id,
        )

    result = asyncio.run(
        run_agent(
            definition,
            identity,
            _task(definition, lead_id),
            registry,
            model_key,
            session_factory,
            check=check,
        )
    )
    used = {
        "stop_reason": result.stop_reason,
        "sources": {result.source_ids[k]: v for k, v in result.sources.items()},
        "model_turns": result.model_turns,
        "tool_call_count": result.tool_calls,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }
    if result.error is not None:
        record(AgentStatus.failed, failure_category=result.error.category, **used)
        if result.error.transient:
            db.commit()
            raise result.error
        return _failed_step(agent_id, result.error.category)
    if result.email is not None:
        return _record_email(db, ctx, record, result, run_id, agent_id, lead_id, used, registry)
    if result.output is None:
        # It reached a budget before it could answer.
        record(AgentStatus.failed, failure_category=result.stop_reason, **used)
        return _failed_step(agent_id, result.stop_reason)

    gated, notes = review(result)
    claims = [
        {"text": c["text"], "evidence_ids": [result.source_ids[i] for i in c["evidence_ids"]]}
        for c in gated.claims
    ]
    status = AgentStatus.completed if claims else AgentStatus.rejected
    record(
        status,
        summary=gated.summary if claims else None,
        claims=claims,
        rejected_claims=gated.rejected_claims,
        missing_information=gated.missing_information if claims else [],
        review_notes=notes,
        failure_category=None,
        **used,
    )
    cost = estimate_cost(
        registry.model(result.served_by or model_key),
        Usage(result.input_tokens, result.output_tokens),
    )
    return {
        "agent_id": str(agent_id),
        "agent_status": status.value,
        "agent_notes": len(notes),
        "usage": {
            "model": result.served_by,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "estimated_cost_usd": cost,
        },
    }


def _email_notes(review: EmailReview, result: AgentResult) -> list[str]:
    notes = []
    if result.stop_reason != "finished":
        notes.append(f"The agent stopped at a limit ({result.stop_reason})")
    if result.refused_calls:
        notes.append(f"{len(result.refused_calls)} tool call(s) were refused or invalid")
    if not result.sources:
        notes.append("The agent read no sources, so nothing it said can be checked")
    return notes


def _record_email(
    db: Session,
    ctx: OrgContext,
    record: Any,
    result: AgentResult,
    run_id: uuid.UUID,
    agent_id: uuid.UUID,
    lead_id: uuid.UUID | None,
    used: dict[str, Any],
    registry: Any,
) -> dict[str, Any]:
    """Stores a draft, never more than that. A rejected email keeps its wording for reviewers."""
    assert result.email is not None and lead_id is not None
    review = check_email(result.email, result.sources)
    notes = _email_notes(review, result)
    usage = {
        "model": result.served_by,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "estimated_cost_usd": estimate_cost(
            registry.model(result.served_by or ""),
            Usage(result.input_tokens, result.output_tokens),
        ),
    }
    if review.fatal:
        record(
            AgentStatus.rejected,
            rejected_claims=[{"text": review.body[:2000], "problems": review.fatal}],
            review_notes=notes,
            failure_category=None,
            **used,
        )
        return {"agent_id": str(agent_id), "agent_status": "rejected", "usage": usage}
    record(AgentStatus.completed, summary=review.subject, review_notes=notes, **used)
    lead = get_lead(db, ctx, lead_id)
    if not lead.email:
        # The address was removed while the agent worked.
        db.execute(
            update(AgentRun)
            .where(AgentRun.id == agent_id)
            .values(status=AgentStatus.failed, failure_category="lead_has_no_email")
        )
        return _failed_step(agent_id, "lead_has_no_email")
    draft = outreach_service.create_agent_draft(
        db,
        ctx,
        lead,
        run_id,
        review.subject,
        review.body,
        flags=review.flags,
        needs_edit=review.needs_edit,
        flagged_contacts=review.flagged_contacts,
        evidence_ids=[result.source_ids[i] for i in review.evidence_ids],
    )
    db.execute(update(AgentRun).where(AgentRun.id == agent_id).values(outreach_draft_id=draft.id))
    return {"agent_id": str(agent_id), "agent_status": "completed", "usage": usage}


def _failed_step(agent_id: uuid.UUID, category: str) -> dict[str, Any]:
    return {"agent_id": str(agent_id), "agent_status": "failed", "agent_failure": category}
