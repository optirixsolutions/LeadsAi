"""Model-written research briefs: gated output, stored apart from the deterministic score.

Local models can take minutes to load, so the request returns at once and the call runs after
the response. This is an in-process task: a restart loses it, and it is reported as failed
once it goes stale. Phase 6 moves it to a durable worker.
"""

import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.evaluation.tasks import PROMPT_VERSION, SynthesisOut, synthesis_messages
from app.agents.gates import check_output, screen_evidence
from app.agents.llm import LLMError, ModelRegistry
from app.core.auth import OrgContext
from app.core.db import get_sessionmaker, set_tenant_context
from app.core.errors import AppError, ConflictError
from app.core.rate_limit import RateLimitedError
from app.models import BriefStatus, Company, EvidenceStatus, Lead, ResearchBrief, ResearchEvidence
from app.services import audit
from app.services.lead_service import lead_with_company

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=10)
MAX_ITEMS = 12
MAX_ITEM_CHARS = 2000
MAX_RUNNING_PER_ORG = 3
# Each brief holds a worker thread for as long as the model takes, and all API routes share that
# pool. Past this limit a brief fails at once, rather than stalling other requests.
_model_slots = threading.BoundedSemaphore(4)


class NoEvidenceError(AppError):
    status_code = 409
    code = "evidence_required"


@lru_cache
def get_registry() -> ModelRegistry:
    return ModelRegistry()


def _now() -> datetime:
    return datetime.now(UTC)


def _expire_stale(db: Session, ctx: OrgContext) -> None:
    db.execute(
        update(ResearchBrief)
        .where(
            ResearchBrief.organization_id == ctx.org_id,
            ResearchBrief.status == BriefStatus.running,
            ResearchBrief.created_at < _now() - STALE_AFTER,
        )
        .values(status=BriefStatus.failed, failure_category="stale", completed_at=_now())
    )


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


def create_brief(db: Session, ctx: OrgContext, lead_id: uuid.UUID) -> ResearchBrief:
    lead_with_company(db, ctx, lead_id)
    if not _usable_evidence(db, ctx.org_id, lead_id):
        raise NoEvidenceError("Add research evidence before requesting a brief")
    _expire_stale(db, ctx)
    running = db.scalar(
        select(func.count())
        .select_from(ResearchBrief)
        .where(
            ResearchBrief.organization_id == ctx.org_id,
            ResearchBrief.status == BriefStatus.running,
            ResearchBrief.lead_id != lead_id,
        )
    )
    if (running or 0) >= MAX_RUNNING_PER_ORG:
        raise RateLimitedError("Several briefs are already being written. Try again shortly.")
    brief = ResearchBrief(
        organization_id=ctx.org_id,
        lead_id=lead_id,
        status=BriefStatus.running,
        model_key=get_registry().routes["synthesis"],
        prompt_version=PROMPT_VERSION,
        created_by_user_id=ctx.user_id,
    )
    db.add(brief)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("A brief is already being written for this lead") from exc
    audit.record(
        db,
        "brief.requested",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="research_brief",
        target_id=brief.id,
        data={"model": brief.model_key},
    )
    return brief


def latest_brief(db: Session, ctx: OrgContext, lead_id: uuid.UUID) -> ResearchBrief | None:
    lead_with_company(db, ctx, lead_id)
    _expire_stale(db, ctx)
    return db.scalar(
        select(ResearchBrief)
        .where(ResearchBrief.organization_id == ctx.org_id, ResearchBrief.lead_id == lead_id)
        .order_by(ResearchBrief.created_at.desc(), ResearchBrief.id)
        .limit(1)
    )


def run_brief(org_id: uuid.UUID, user_id: uuid.UUID, brief_id: uuid.UUID) -> None:
    """Runs after the response, with its own session and the requester's tenant context."""
    with get_sessionmaker()() as db:
        if not _model_slots.acquire(blocking=False):
            _finish(db, org_id, user_id, brief_id, {"status": BriefStatus.failed}, "busy")
            return
        try:
            _run(db, org_id, user_id, brief_id)
        except Exception as exc:
            log.exception("brief_failed", extra={"error_type": type(exc).__name__})
            db.rollback()
            _finish(db, org_id, user_id, brief_id, {"status": BriefStatus.failed}, "error")
        finally:
            _model_slots.release()


def _finish(
    db: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    brief_id: uuid.UUID,
    outcome: dict[str, object],
    failure: str | None = None,
) -> None:
    """Record the result, unless the brief already ended (for example, it went stale)."""
    if failure:
        outcome = {**outcome, "failure_category": failure}
    set_tenant_context(db, user_id=user_id, org_id=org_id)
    updated = db.scalar(
        update(ResearchBrief)
        .where(ResearchBrief.id == brief_id, ResearchBrief.status == BriefStatus.running)
        .values(completed_at=_now(), **outcome)
        .returning(ResearchBrief.id)
    )
    if updated is None:
        db.rollback()
        return
    audit.record(
        db,
        "brief.completed",
        org_id=org_id,
        actor_id=user_id,
        target_type="research_brief",
        target_id=brief_id,
        data={
            "status": getattr(outcome["status"], "value", str(outcome["status"])),
            "failure": outcome.get("failure_category"),
            "kept": len(outcome.get("claims", [])),  # type: ignore[arg-type]
            "rejected": len(outcome.get("rejected_claims", [])),  # type: ignore[arg-type]
        },
    )
    db.commit()


def _run(db: Session, org_id: uuid.UUID, user_id: uuid.UUID, brief_id: uuid.UUID) -> None:
    set_tenant_context(db, user_id=user_id, org_id=org_id)
    brief = db.get(ResearchBrief, brief_id)
    if brief is None or brief.status != BriefStatus.running:
        return
    lead = db.get(Lead, brief.lead_id)
    if lead is None or lead.deleted_at is not None:
        _finish(db, org_id, user_id, brief_id, {"status": BriefStatus.failed}, "lead_deleted")
        return
    company = db.get(Company, lead.company_id) if lead.company_id else None
    # The same rule as CRM fields in scoring: a name that reads like instructions is not used.
    company_name = company.name if company and not screen_evidence(company.name) else None
    rows = _usable_evidence(db, org_id, brief.lead_id)
    # Short labels keep the prompt small and stop the model from echoing real row IDs.
    labelled = {f"E{i}": r for i, r in enumerate(rows, start=1)}
    shown = {label: r.content[:MAX_ITEM_CHARS] for label, r in labelled.items()}
    item = {
        "company": company_name or "Unknown company",
        "evidence": [
            {"id": label, "source": labelled[label].source_type.value, "text": text}
            for label, text in shown.items()
        ],
    }
    model_key = brief.model_key
    # A local model call can run for minutes; do not hold a connection or locks across it.
    db.commit()

    outcome: dict[str, object] = {"status": BriefStatus.failed}
    try:
        parsed, result = get_registry().structured(
            model_key, synthesis_messages(item), SynthesisOut
        )
    except LLMError as exc:
        outcome["failure_category"] = exc.category
    else:
        gated = check_output(parsed, shown)
        claims = [
            {"text": c["text"], "evidence_ids": [str(labelled[i].id) for i in c["evidence_ids"]]}
            for c in gated.claims
        ]
        outcome = {
            "status": BriefStatus.completed if claims else BriefStatus.rejected,
            "served_by": result.model_key,
            "summary": gated.summary if claims else None,
            "claims": claims,
            "rejected_claims": gated.rejected_claims,
            "missing_information": gated.missing_information if claims else [],
            "evidence_ids": [r.id for r in rows],
            "latency_ms": round(result.latency_ms),
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
        }

    _finish(db, org_id, user_id, brief_id, outcome)
