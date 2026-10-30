"""Model-written research briefs: gated output, stored apart from the deterministic score.

A brief is written by a workflow step on a worker, so it survives API restarts. Each run has at
most one brief, which is what makes a repeated step safe: a finished brief is simply returned.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.evaluation.tasks import PROMPT_VERSION, SynthesisOut, synthesis_messages
from app.agents.gates import check_output, screen_evidence
from app.agents.llm import LLMError, ModelRegistry
from app.agents.llm.registry import estimate_cost
from app.core.auth import OrgContext
from app.core.db import set_tenant_context
from app.core.errors import AppError, ConflictError, LeaseLostError
from app.models import (
    BriefStatus,
    Company,
    EvidenceStatus,
    Lead,
    ResearchBrief,
    ResearchEvidence,
    WorkflowKind,
    WorkflowRun,
    WorkflowStatus,
)
from app.services import workflow_service
from app.services.lead_service import lead_with_company

MAX_ITEMS = 12
MAX_ITEM_CHARS = 2000
_ENDED_RUNS = (WorkflowStatus.failed, WorkflowStatus.cancelled)


class NoEvidenceError(AppError):
    status_code = 409
    code = "evidence_required"


@dataclass(frozen=True)
class BriefOutcome:
    brief_id: uuid.UUID
    status: BriefStatus
    failure: str | None
    usage: dict[str, Any]


@lru_cache
def get_registry() -> ModelRegistry:
    return ModelRegistry()


def _now() -> datetime:
    return datetime.now(UTC)


def _usable_evidence(db: Session, org_id: uuid.UUID, lead_id: uuid.UUID) -> list[ResearchEvidence]:
    """Newest accepted items. Quarantined text never reaches a model."""
    return list(
        db.scalars(
            select(ResearchEvidence)
            .where(
                ResearchEvidence.organization_id == org_id,
                ResearchEvidence.lead_id == lead_id,
                ResearchEvidence.status == EvidenceStatus.accepted,
            )
            .order_by(ResearchEvidence.observed_at.desc(), ResearchEvidence.id)
            .limit(MAX_ITEMS)
        )
    )


def _new_brief(ctx: OrgContext, lead_id: uuid.UUID, run_id: uuid.UUID) -> ResearchBrief:
    return ResearchBrief(
        organization_id=ctx.org_id,
        lead_id=lead_id,
        workflow_run_id=run_id,
        status=BriefStatus.running,
        model_key=get_registry().routes["synthesis"],
        prompt_version=PROMPT_VERSION,
        created_by_user_id=ctx.user_id,
    )


def _end_abandoned(db: Session, ctx: OrgContext, lead_id: uuid.UUID) -> None:
    """A run can end with no worker left to tidy up (it exhausted its attempts, for example).
    Its brief must not stay `running`, as that would block every later brief for the lead."""
    db.execute(
        update(ResearchBrief)
        .where(
            ResearchBrief.organization_id == ctx.org_id,
            ResearchBrief.lead_id == lead_id,
            ResearchBrief.status == BriefStatus.running,
            ~exists().where(
                WorkflowRun.id == ResearchBrief.workflow_run_id,
                WorkflowRun.status.not_in(_ENDED_RUNS),
            ),
        )
        .values(status=BriefStatus.failed, failure_category="abandoned", completed_at=_now())
    )


def create_brief(db: Session, ctx: OrgContext, lead_id: uuid.UUID) -> ResearchBrief:
    """Queue a research run and show its brief as in progress straight away."""
    lead_with_company(db, ctx, lead_id)
    if not _usable_evidence(db, ctx.org_id, lead_id):
        raise NoEvidenceError("Add research evidence before requesting a brief")
    _end_abandoned(db, ctx, lead_id)
    run = workflow_service.enqueue(db, ctx, lead_id, WorkflowKind.research)
    brief = _new_brief(ctx, lead_id, run.id)
    db.add(brief)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("A brief is already being written for this lead") from exc
    return brief


def latest_brief(db: Session, ctx: OrgContext, lead_id: uuid.UUID) -> ResearchBrief | None:
    lead_with_company(db, ctx, lead_id)
    _end_abandoned(db, ctx, lead_id)
    brief = db.scalar(
        select(ResearchBrief)
        .where(ResearchBrief.organization_id == ctx.org_id, ResearchBrief.lead_id == lead_id)
        .order_by(ResearchBrief.created_at.desc(), ResearchBrief.id)
        .limit(1)
    )
    return brief


def write_brief(
    db: Session, ctx: OrgContext, lead_id: uuid.UUID, run_id: uuid.UUID, *, owner: str
) -> BriefOutcome:
    """Workflow step. A transient model failure is raised, which fails the run until resumed."""
    _end_abandoned(db, ctx, lead_id)
    brief = db.scalar(select(ResearchBrief).where(ResearchBrief.workflow_run_id == run_id))
    if brief is None:
        brief = _new_brief(ctx, lead_id, run_id)
        db.add(brief)
        db.flush()
    elif brief.status in (BriefStatus.completed, BriefStatus.rejected):
        return BriefOutcome(brief.id, brief.status, None, {})
    brief_id = brief.id
    brief.status = BriefStatus.running
    brief.failure_category = None

    lead = db.get(Lead, lead_id)
    company = db.get(Company, lead.company_id) if lead and lead.company_id else None
    # The same rule as CRM fields in scoring: a name that reads like instructions is not used.
    company_name = company.name if company and not screen_evidence(company.name) else None
    rows = _usable_evidence(db, ctx.org_id, lead_id)
    # Short labels keep the prompt small and stop the model from echoing real row IDs.
    labelled = {f"E{i}": r for i, r in enumerate(rows, start=1)}
    shown = {label: r.content[:MAX_ITEM_CHARS] for label, r in labelled.items()}
    source_ids = {label: str(r.id) for label, r in labelled.items()}
    sources = {label: r.source_type.value for label, r in labelled.items()}
    evidence_ids = [r.id for r in rows]
    model_key = brief.model_key
    # A local model call can run for minutes; do not hold a connection or locks across it.
    db.commit()

    def record(status: BriefStatus, **values: Any) -> None:
        # A model call can outlast this worker's lease. If another worker took the run over,
        # its answer stands and this late one is dropped.
        set_tenant_context(db, user_id=ctx.user_id, org_id=ctx.org_id)
        updated = db.scalar(
            update(ResearchBrief)
            .where(
                ResearchBrief.id == brief_id,
                exists().where(WorkflowRun.id == run_id, WorkflowRun.lease_owner == owner),
            )
            .values(status=status, completed_at=_now(), **values)
            .returning(ResearchBrief.id)
        )
        if updated is None:
            db.rollback()
            raise LeaseLostError

    if not shown:
        record(BriefStatus.failed, failure_category="evidence_required")
        return BriefOutcome(brief_id, BriefStatus.failed, "evidence_required", {})

    item = {
        "company": company_name or "Unknown company",
        "evidence": [
            {"id": label, "source": sources[label], "text": text} for label, text in shown.items()
        ],
    }
    registry = get_registry()
    try:
        parsed, result = registry.structured(model_key, synthesis_messages(item), SynthesisOut)
    except LLMError as exc:
        record(BriefStatus.failed, failure_category=exc.category)
        if exc.transient:
            db.commit()
            raise
        return BriefOutcome(brief_id, BriefStatus.failed, exc.category, {})

    gated = check_output(parsed, shown)
    claims = [
        {"text": c["text"], "evidence_ids": [source_ids[i] for i in c["evidence_ids"]]}
        for c in gated.claims
    ]
    status = BriefStatus.completed if claims else BriefStatus.rejected
    record(
        status,
        served_by=result.model_key,
        summary=gated.summary if claims else None,
        claims=claims,
        rejected_claims=gated.rejected_claims,
        missing_information=gated.missing_information if claims else [],
        evidence_ids=evidence_ids,
        latency_ms=round(result.latency_ms),
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        failure_category=None,
    )
    usage = {
        "model": result.model_key,
        "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
        "estimated_cost_usd": estimate_cost(registry.model(result.model_key), result.usage),
    }
    return BriefOutcome(brief_id, status, None, usage)
