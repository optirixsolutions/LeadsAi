"""ICP versions, research evidence, and assessments. Tenant-scoped through OrgContext."""

import hashlib
import unicodedata
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.gates import screen_evidence
from app.core.auth import OrgContext, restore_context
from app.core.errors import AppError, ConflictError, NotFoundError
from app.integrations.fetcher import get_fetcher
from app.models import (
    ActivityType,
    Company,
    EvaluationStatus,
    EvidenceSource,
    EvidenceStatus,
    IcpConfiguration,
    Lead,
    LeadAssessment,
    ResearchEvidence,
)
from app.schemas.intelligence import EvidenceCreate, IcpCreate, as_dict
from app.services import audit, scoring
from app.services.lead_service import get_lead, lead_with_company, record_activity


class NoIcpError(AppError):
    status_code = 409
    code = "icp_required"


class EvidenceLimitError(AppError):
    status_code = 409
    code = "evidence_limit"


MAX_EVIDENCE_PER_LEAD = 500
# Newest items a score reads, so a very long history cannot make every assessment expensive.
MAX_SCORED_ITEMS = 200


def _now() -> datetime:
    return datetime.now(UTC)


def _fingerprint(content: str) -> str:
    """Case and spacing changes count as the same text, so they cannot dodge a rejection."""
    canonical = " ".join(unicodedata.normalize("NFKC", content).casefold().split())
    return hashlib.sha256(canonical.encode()).hexdigest()


def _check_capacity(db: Session, ctx: OrgContext, lead_id: uuid.UUID) -> None:
    count = db.scalar(
        select(func.count())
        .select_from(ResearchEvidence)
        .where(ResearchEvidence.organization_id == ctx.org_id, ResearchEvidence.lead_id == lead_id)
    )
    if (count or 0) >= MAX_EVIDENCE_PER_LEAD:
        raise EvidenceLimitError("This lead already has the maximum amount of evidence")


# --- ICP --------------------------------------------------------------------------------


def active_icp(db: Session, ctx: OrgContext) -> IcpConfiguration | None:
    return db.scalar(
        select(IcpConfiguration)
        .where(IcpConfiguration.organization_id == ctx.org_id)
        .order_by(IcpConfiguration.version.desc())
        .limit(1)
    )


def list_icp_versions(db: Session, ctx: OrgContext) -> list[IcpConfiguration]:
    return list(
        db.scalars(
            select(IcpConfiguration)
            .where(IcpConfiguration.organization_id == ctx.org_id)
            .order_by(IcpConfiguration.version.desc())
            .limit(50)
        )
    )


def create_icp(db: Session, ctx: OrgContext, body: IcpCreate) -> IcpConfiguration:
    current = db.scalar(
        select(func.max(IcpConfiguration.version)).where(
            IcpConfiguration.organization_id == ctx.org_id
        )
    )
    version = (current or 0) + 1
    icp = IcpConfiguration(
        organization_id=ctx.org_id,
        version=version,
        criteria=as_dict(body.criteria),
        weights=as_dict(body.weights),
        created_by_user_id=ctx.user_id,
    )
    db.add(icp)
    try:
        db.flush()
    except IntegrityError as exc:
        # Two admins saving at once: the loser retries against the new version.
        raise ConflictError("Someone else just saved the ICP. Reload and try again.") from exc
    audit.record(
        db,
        "icp.version_created",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="icp_configuration",
        target_id=icp.id,
        data={"version": version},
    )
    return icp


# --- evidence ---------------------------------------------------------------------------


def _store(
    db: Session,
    ctx: OrgContext,
    lead_id: uuid.UUID,
    *,
    source: EvidenceSource,
    content: str,
    observed_at: datetime,
    source_url: str | None = None,
    title: str | None = None,
) -> tuple[ResearchEvidence, bool]:
    """Insert one item after screening it. Returns (row, created); repeats return the original."""
    digest = _fingerprint(content)
    flags = screen_evidence(f"{title or ''}\n{content}")
    new_id = db.scalar(
        insert(ResearchEvidence)
        .values(
            id=uuid.uuid4(),
            organization_id=ctx.org_id,
            lead_id=lead_id,
            source_type=source,
            source_url=source_url,
            title=title,
            content=content,
            content_hash=digest,
            status=EvidenceStatus.quarantined if flags else EvidenceStatus.accepted,
            screen_flags=flags,
            observed_at=observed_at,
            created_by_user_id=ctx.user_id,
        )
        .on_conflict_do_nothing()
        .returning(ResearchEvidence.id)
    )
    row = db.scalar(
        select(ResearchEvidence).where(
            ResearchEvidence.organization_id == ctx.org_id,
            ResearchEvidence.lead_id == lead_id,
            ResearchEvidence.source_type == source,
            ResearchEvidence.content_hash == digest,
        )
    )
    assert row is not None
    return row, new_id is not None


def _record_added(
    db: Session, ctx: OrgContext, row: ResearchEvidence, *, created: bool
) -> ResearchEvidence:
    if created:
        record_activity(
            db,
            ctx,
            ActivityType.research_added,
            lead_id=row.lead_id,
            data={
                "evidence_id": str(row.id),
                "source": row.source_type.value,
                "status": row.status.value,
            },
        )
        audit.record(
            db,
            "evidence.added",
            org_id=ctx.org_id,
            actor_id=ctx.user_id,
            target_type="research_evidence",
            target_id=row.id,
            data={
                "source": row.source_type.value,
                "status": row.status.value,
                "flags": row.screen_flags,
            },
        )
    return row


def list_evidence(db: Session, ctx: OrgContext, lead_id: uuid.UUID) -> list[ResearchEvidence]:
    get_lead(db, ctx, lead_id)
    return list(
        db.scalars(
            select(ResearchEvidence)
            .where(
                ResearchEvidence.organization_id == ctx.org_id, ResearchEvidence.lead_id == lead_id
            )
            .order_by(ResearchEvidence.created_at.desc(), ResearchEvidence.id)
            .limit(500)
        )
    )


def add_evidence(
    db: Session, ctx: OrgContext, lead_id: uuid.UUID, body: EvidenceCreate
) -> ResearchEvidence:
    get_lead(db, ctx, lead_id)
    _check_capacity(db, ctx, lead_id)
    row, created = _store(
        db,
        ctx,
        lead_id,
        source=EvidenceSource.manual_note,
        content=body.content,
        observed_at=body.observed_at or _now(),
        source_url=body.source_url,
        title=body.title,
    )
    return _record_added(db, ctx, row, created=created)


def _domain_allowlist(domain: str) -> Callable[[str], bool]:
    return lambda host: host == domain or host.endswith(f".{domain}")


def fetch_evidence(db: Session, ctx: OrgContext, lead_id: uuid.UUID, url: str) -> ResearchEvidence:
    """Fetch a page on the lead's own company domain and store its text as evidence."""
    _, company = lead_with_company(db, ctx, lead_id)
    if company is None or not company.domain:
        raise AppError(
            "Add a company domain to this lead before fetching pages",
            code="company_domain_required",
        )
    allowed = _domain_allowlist(company.domain)
    # The network call can take seconds, so no transaction stays open across it.
    db.commit()
    page = get_fetcher().fetch(url, allowed)
    restore_context(db, ctx)
    get_lead(db, ctx, lead_id)
    _check_capacity(db, ctx, lead_id)
    row, created = _store(
        db,
        ctx,
        lead_id,
        source=EvidenceSource.fetched_page,
        content=page.text,
        observed_at=_now(),
        source_url=page.url,
        title=page.title,
    )
    return _record_added(db, ctx, row, created=created)


def get_evidence(
    db: Session, ctx: OrgContext, lead_id: uuid.UUID, evidence_id: uuid.UUID
) -> ResearchEvidence:
    row = db.scalar(
        select(ResearchEvidence).where(
            ResearchEvidence.id == evidence_id,
            ResearchEvidence.organization_id == ctx.org_id,
            ResearchEvidence.lead_id == lead_id,
        )
    )
    if row is None:
        raise NotFoundError("Evidence not found")
    return row


def review_evidence(
    db: Session,
    ctx: OrgContext,
    lead_id: uuid.UUID,
    evidence_id: uuid.UUID,
    status: EvidenceStatus,
) -> ResearchEvidence:
    get_lead(db, ctx, lead_id)
    row = get_evidence(db, ctx, lead_id, evidence_id)
    previous = row.status
    row.status = status
    row.reviewed_by_user_id = ctx.user_id
    row.reviewed_at = _now()
    audit.record(
        db,
        "evidence.reviewed",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="research_evidence",
        target_id=row.id,
        data={"from": previous.value, "to": status.value, "flags": row.screen_flags},
    )
    return row


# --- assessment -------------------------------------------------------------------------


def _crm_facts(
    db: Session, ctx: OrgContext, lead: Lead, company: Company | None
) -> dict[str, scoring.Fact]:
    """Store each CRM field as evidence, so scores trace to the value they actually used."""
    now = _now()
    fields: list[tuple[str, str, str | int | None]] = [
        ("email", "Email on file", "yes" if lead.email else None),
        ("title", "Job title", lead.title),
        ("company", "Company", company.name if company else None),
        ("industry", "Industry", company.industry if company else None),
        ("employee_count", "Employee count", company.employee_count if company else None),
        ("country", "Country", company.country if company else None),
    ]
    facts: dict[str, scoring.Fact] = {}
    for key, label, value in fields:
        if value is None or value == "":
            continue
        row, created = _store(
            db,
            ctx,
            lead.id,
            source=EvidenceSource.crm_record,
            content=f"{label}: {value}",
            observed_at=now,
        )
        _record_added(db, ctx, row, created=created)
        # CRM text can come from a CSV, so a field that reads like instructions is not used.
        if row.status == EvidenceStatus.accepted:
            facts[key] = scoring.Fact(value=value, evidence_id=str(row.id))
    return facts


def assess_lead(
    db: Session, ctx: OrgContext, lead_id: uuid.UUID, *, workflow_run_id: uuid.UUID | None = None
) -> LeadAssessment:
    """Score now. With a run ID, a repeat returns that run's existing result instead."""
    if workflow_run_id is not None:
        existing = db.scalar(
            select(LeadAssessment).where(LeadAssessment.workflow_run_id == workflow_run_id)
        )
        if existing is not None:
            return existing
    lead, company = lead_with_company(db, ctx, lead_id)
    icp = active_icp(db, ctx)
    if icp is None:
        raise NoIcpError("Set up your ideal customer profile before assessing leads")
    facts = _crm_facts(db, ctx, lead, company)
    db.flush()
    rows = db.scalars(
        select(ResearchEvidence)
        .where(
            ResearchEvidence.organization_id == ctx.org_id,
            ResearchEvidence.lead_id == lead.id,
            ResearchEvidence.status == EvidenceStatus.accepted,
        )
        .order_by(ResearchEvidence.observed_at.desc(), ResearchEvidence.id)
        .limit(MAX_SCORED_ITEMS)
    )
    items = [
        scoring.EvidenceItem(
            id=str(r.id),
            text=r.content,
            observed_at=r.observed_at,
            source_type=r.source_type.value,
            source_url=r.source_url,
        )
        for r in rows
    ]
    result = scoring.score_lead(facts, items, icp.criteria, icp.weights, now=_now())
    assessment = LeadAssessment(
        organization_id=ctx.org_id,
        lead_id=lead.id,
        icp_configuration_id=icp.id,
        workflow_run_id=workflow_run_id,
        score=result.score,
        fit=result.fit,
        components=result.components,
        reasons=result.reasons,
        positive_signals=result.positive_signals,
        negative_signals=result.negative_signals,
        missing_information=result.missing_information,
        evidence_ids=[uuid.UUID(i) for i in result.evidence_ids],
        model_version=f"{scoring.ENGINE_VERSION}/icp-v{icp.version}",
        evaluation_status=result.status,
        created_by_user_id=ctx.user_id,
    )
    db.add(assessment)
    db.flush()
    record_activity(
        db,
        ctx,
        ActivityType.assessed,
        lead_id=lead.id,
        data={"assessment_id": str(assessment.id), "score": result.score, "fit": result.fit.value},
    )
    audit.record(
        db,
        "assessment.created",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="lead_assessment",
        target_id=assessment.id,
        data={"score": result.score, "fit": result.fit.value, "icp_version": icp.version},
    )
    return assessment


def list_assessments(db: Session, ctx: OrgContext, lead_id: uuid.UUID) -> list[LeadAssessment]:
    get_lead(db, ctx, lead_id)
    return list(
        db.scalars(
            select(LeadAssessment)
            .where(LeadAssessment.organization_id == ctx.org_id, LeadAssessment.lead_id == lead_id)
            .order_by(LeadAssessment.created_at.desc(), LeadAssessment.id)
            .limit(50)
        )
    )


def get_assessment(db: Session, ctx: OrgContext, assessment_id: uuid.UUID) -> LeadAssessment:
    row = db.scalar(
        select(LeadAssessment).where(
            LeadAssessment.id == assessment_id, LeadAssessment.organization_id == ctx.org_id
        )
    )
    if row is None:
        raise NotFoundError("Assessment not found")
    # An assessment of a deleted lead is gone with the lead, same as its other records.
    get_lead(db, ctx, row.lead_id)
    return row


def assessment_evidence(
    db: Session, ctx: OrgContext, assessment: LeadAssessment
) -> list[ResearchEvidence]:
    if not assessment.evidence_ids:
        return []
    return list(
        db.scalars(
            select(ResearchEvidence).where(
                ResearchEvidence.organization_id == ctx.org_id,
                ResearchEvidence.id.in_(assessment.evidence_ids),
            )
        )
    )


def review_assessment(
    db: Session, ctx: OrgContext, assessment_id: uuid.UUID, status: EvaluationStatus
) -> LeadAssessment:
    row = get_assessment(db, ctx, assessment_id)
    previous = row.evaluation_status
    row.evaluation_status = status
    row.reviewed_by_user_id = ctx.user_id
    row.reviewed_at = _now()
    audit.record(
        db,
        "assessment.reviewed",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="lead_assessment",
        target_id=row.id,
        data={"from": previous.value, "to": status.value},
    )
    return row
