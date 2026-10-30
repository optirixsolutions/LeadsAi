"""The tool catalog. Each tool wraps a real service, which does its own tenant scoping.

Not here yet, because what they would act on does not exist: outreach drafts (Phase 8), follow-up
tasks, and integration health (Phase 10). There is deliberately no SQL, shell, file, or
general HTTP tool. Quarantined and rejected evidence is never returned.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import OrgContext
from app.core.errors import NotFoundError
from app.core.permissions import Permission
from app.mcp.registry import ToolSpec
from app.models import (
    Company,
    EvidenceStatus,
    Lead,
    Opportunity,
    PipelineStage,
    ResearchEvidence,
    StageKind,
    WorkflowKind,
)
from app.schemas.crm import LeadCreate, LeadUpdate
from app.schemas.intelligence import EvidenceCreate
from app.services import intelligence_service, lead_service, pipeline_service, workflow_service
from app.services.lead_service import LeadFilters

MAX_ITEMS = 25
MAX_TEXT_CHARS = 2000


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NoInput(_In):
    pass


class LeadRef(_In):
    lead_id: uuid.UUID


class SearchLeadsIn(_In):
    query: str | None = Field(default=None, max_length=200, description="Name, email, or company")
    limit: int = Field(default=10, ge=1, le=MAX_ITEMS)


class LeadSummary(BaseModel):
    id: uuid.UUID
    name: str
    title: str | None
    company: str | None
    status: str


class SearchLeadsOut(BaseModel):
    items: list[LeadSummary]
    total: int


def _name(lead: Lead) -> str:
    return " ".join(p for p in (lead.first_name, lead.last_name) if p) or (lead.email or "Unnamed")


def _summary(lead: Lead, company: Company | None) -> LeadSummary:
    return LeadSummary(
        id=lead.id,
        name=_name(lead),
        title=lead.title,
        company=company.name if company else None,
        status=lead.status.value,
    )


def search_leads(db: Session, ctx: OrgContext, args: SearchLeadsIn) -> SearchLeadsOut:
    rows, _, total = lead_service.list_leads(
        db, ctx, LeadFilters(q=args.query), sort="-created_at", limit=args.limit, cursor=None
    )
    return SearchLeadsOut(items=[_summary(lead, company) for lead, company in rows], total=total)


class LeadProfile(LeadSummary):
    email: str | None
    company_domain: str | None
    industry: str | None
    employee_count: int | None
    country: str | None
    tags: list[str]


def get_lead_profile(db: Session, ctx: OrgContext, args: LeadRef) -> LeadProfile:
    lead, company = lead_service.lead_with_company(db, ctx, args.lead_id)
    return LeadProfile(
        **_summary(lead, company).model_dump(),
        email=lead.email,
        company_domain=company.domain if company else None,
        industry=company.industry if company else None,
        employee_count=company.employee_count if company else None,
        country=company.country if company else None,
        tags=lead.tags,
    )


def _profile_sources(out: LeadProfile) -> dict[str, str]:
    facts = {
        "Title": out.title,
        "Company": out.company,
        "Industry": out.industry,
        "Employees": out.employee_count,
        "Country": out.country,
    }
    known = [f"{k}: {v}" for k, v in facts.items() if v not in (None, "")]
    return {f"lead:{out.id}": ". ".join(known)} if known else {}


class CreateLeadIn(_In):
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    title: str | None = Field(default=None, max_length=200)
    company_name: str | None = Field(default=None, max_length=200)


def create_lead(db: Session, ctx: OrgContext, args: CreateLeadIn) -> LeadSummary:
    lead = lead_service.create_lead(db, ctx, LeadCreate(**args.model_dump(), source="mcp"))
    return get_lead_profile(db, ctx, LeadRef(lead_id=lead.id))


class UpdateLeadIn(_In):
    lead_id: uuid.UUID
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)


def update_lead(db: Session, ctx: OrgContext, args: UpdateLeadIn) -> LeadSummary:
    """Contact details only. A status change goes through request_action_approval."""
    fields = args.model_dump(exclude={"lead_id"}, exclude_none=True)
    lead_service.update_lead(db, ctx, args.lead_id, LeadUpdate(**fields))
    return get_lead_profile(db, ctx, LeadRef(lead_id=args.lead_id))


class ListActivitiesIn(_In):
    lead_id: uuid.UUID
    limit: int = Field(default=20, ge=1, le=MAX_ITEMS)


class ActivityItem(BaseModel):
    id: uuid.UUID
    type: str
    body: str | None
    created_at: datetime


class ActivitiesOut(BaseModel):
    items: list[ActivityItem]


def list_lead_activities(db: Session, ctx: OrgContext, args: ListActivitiesIn) -> ActivitiesOut:
    lead_service.get_lead(db, ctx, args.lead_id)
    rows = lead_service.lead_timeline(db, ctx, args.lead_id)[0][: args.limit]
    return ActivitiesOut(
        items=[
            ActivityItem(
                id=a.id,
                type=a.type.value,
                body=a.body[:MAX_TEXT_CHARS] if a.body else None,
                created_at=a.created_at,
            )
            for a in rows
        ]
    )


class EvidenceItem(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    source_type: str
    source_url: str | None
    content: str
    observed_at: datetime


class EvidenceListOut(BaseModel):
    items: list[EvidenceItem]


def _evidence_out(rows: Any) -> EvidenceListOut:
    return EvidenceListOut(
        items=[
            EvidenceItem(
                id=r.id,
                lead_id=r.lead_id,
                source_type=r.source_type.value,
                source_url=r.source_url,
                content=r.content[:MAX_TEXT_CHARS],
                observed_at=r.observed_at,
            )
            for r in rows
        ]
    )


def _evidence_sources(out: EvidenceListOut) -> dict[str, str]:
    return {str(i.id): i.content for i in out.items}


def get_research_evidence(db: Session, ctx: OrgContext, args: LeadRef) -> EvidenceListOut:
    lead_service.get_lead(db, ctx, args.lead_id)
    return _evidence_out(
        db.scalars(
            select(ResearchEvidence)
            .where(
                ResearchEvidence.organization_id == ctx.org_id,
                ResearchEvidence.lead_id == args.lead_id,
                ResearchEvidence.status == EvidenceStatus.accepted,
            )
            .order_by(ResearchEvidence.observed_at.desc(), ResearchEvidence.id)
            .limit(MAX_ITEMS)
        )
    )


class SearchResearchIn(_In):
    query: str = Field(min_length=2, max_length=200)
    lead_id: uuid.UUID | None = None


def search_company_research(
    db: Session, ctx: OrgContext, args: SearchResearchIn
) -> EvidenceListOut:
    pattern = f"%{lead_service._escape_like(args.query)}%"
    stmt = (
        select(ResearchEvidence)
        .join(Lead, Lead.id == ResearchEvidence.lead_id)
        .where(
            ResearchEvidence.organization_id == ctx.org_id,
            ResearchEvidence.status == EvidenceStatus.accepted,
            Lead.deleted_at.is_(None),
            ResearchEvidence.content.ilike(pattern, escape="\\"),
        )
    )
    if args.lead_id:
        stmt = stmt.where(ResearchEvidence.lead_id == args.lead_id)
    return _evidence_out(
        db.scalars(stmt.order_by(ResearchEvidence.observed_at.desc()).limit(MAX_ITEMS))
    )


class SaveEvidenceIn(_In):
    lead_id: uuid.UUID
    content: str = Field(min_length=1, max_length=20_000)
    source_url: str | None = Field(default=None, max_length=2048)


class SavedEvidence(BaseModel):
    id: uuid.UUID
    status: str
    screen_flags: list[str]


def save_research_evidence(db: Session, ctx: OrgContext, args: SaveEvidenceIn) -> SavedEvidence:
    """Screened like any other evidence, so instruction-like text is quarantined."""
    row = intelligence_service.add_evidence(
        db, ctx, args.lead_id, EvidenceCreate(content=args.content, source_url=args.source_url)
    )
    return SavedEvidence(id=row.id, status=row.status.value, screen_flags=row.screen_flags)


class ScoreOut(BaseModel):
    assessment_id: uuid.UUID
    score: int
    fit: str
    evaluation_status: str
    reasons: list[str]
    missing_information: list[str]
    model_version: str


def _score_out(a: Any) -> ScoreOut:
    return ScoreOut(
        assessment_id=a.id,
        score=a.score,
        fit=a.fit.value,
        evaluation_status=a.evaluation_status.value,
        reasons=[r["text"] for r in a.reasons],
        missing_information=a.missing_information,
        model_version=a.model_version,
    )


def _score_sources(out: ScoreOut) -> dict[str, str]:
    lines = [f"Score {out.score} of 100, {out.fit} fit.", *out.reasons, *out.missing_information]
    return {f"score:{out.assessment_id}": " ".join(lines)}


def get_lead_score(db: Session, ctx: OrgContext, args: LeadRef) -> ScoreOut:
    rows = intelligence_service.list_assessments(db, ctx, args.lead_id)
    if not rows:
        raise NotFoundError("This lead has not been assessed yet")
    return _score_out(rows[0])


def evaluate_lead_fit(db: Session, ctx: OrgContext, args: LeadRef) -> ScoreOut:
    return _score_out(intelligence_service.assess_lead(db, ctx, args.lead_id))


class IcpOut(BaseModel):
    version: int
    criteria: dict[str, Any]
    weights: dict[str, Any]


def get_icp_configuration(db: Session, ctx: OrgContext, _: NoInput) -> IcpOut:
    icp = intelligence_service.active_icp(db, ctx)
    if icp is None:
        raise NotFoundError("No ideal customer profile has been set up")
    return IcpOut(version=icp.version, criteria=icp.criteria, weights=icp.weights)


def _icp_sources(out: IcpOut) -> dict[str, str]:
    known = {k: v for k, v in out.criteria.items() if v not in (None, [])}
    return {f"icp:{out.version}": f"ICP criteria: {known}"}


class StageTotals(BaseModel):
    name: str
    kind: str
    count: int
    totals: dict[str, str]


class PipelineOut(BaseModel):
    stages: list[StageTotals]


def get_pipeline_summary(db: Session, ctx: OrgContext, _: NoInput) -> PipelineOut:
    stages = pipeline_service.pipeline_summary(db, ctx)
    return PipelineOut(
        stages=[
            StageTotals(
                name=s.name,
                kind=s.kind.value,
                count=s.count,
                totals={k: str(v) for k, v in s.totals.items()},
            )
            for s in stages
        ]
    )


def _pipeline_sources(out: PipelineOut) -> dict[str, str]:
    lines = [
        f"{s.name} ({s.kind}): {s.count} opportunities, totals {s.totals or 'none'}."
        for s in out.stages
    ]
    return {"pipeline:summary": " ".join(lines)}


class ListOpportunitiesIn(_In):
    limit: int = Field(default=25, ge=1, le=MAX_ITEMS)


class OpportunityItem(BaseModel):
    id: uuid.UUID
    name: str
    stage: str
    amount: str | None
    currency: str
    expected_close_date: str | None
    days_since_update: int


class OpportunitiesOut(BaseModel):
    items: list[OpportunityItem]


def _opportunity_item(opp: Opportunity, stage: str) -> OpportunityItem:
    age = datetime.now(opp.updated_at.tzinfo) - opp.updated_at
    return OpportunityItem(
        id=opp.id,
        name=opp.name,
        stage=stage,
        amount=str(opp.amount) if opp.amount is not None else None,
        currency=opp.currency,
        expected_close_date=str(opp.expected_close_date) if opp.expected_close_date else None,
        days_since_update=age.days,
    )


def list_open_opportunities(
    db: Session, ctx: OrgContext, args: ListOpportunitiesIn
) -> OpportunitiesOut:
    """Least recently updated first, which is where stale deals are."""
    rows = db.execute(
        select(Opportunity, PipelineStage.name)
        .join(PipelineStage, PipelineStage.id == Opportunity.stage_id)
        .where(Opportunity.organization_id == ctx.org_id, PipelineStage.kind == StageKind.open)
        .order_by(Opportunity.updated_at)
        .limit(args.limit)
    ).all()
    return OpportunitiesOut(items=[_opportunity_item(o, stage) for o, stage in rows])


def _opportunity_sources(out: OpportunitiesOut) -> dict[str, str]:
    return {
        f"opportunity:{o.id}": (
            f"{o.name} in {o.stage}, amount {o.amount or 'unknown'} {o.currency}, "
            f"last updated {o.days_since_update} days ago."
        )
        for o in out.items
    }


class OpportunityRef(_In):
    opportunity_id: uuid.UUID


def get_opportunity_details(db: Session, ctx: OrgContext, args: OpportunityRef) -> OpportunityItem:
    opp = pipeline_service.get_opportunity(db, ctx, args.opportunity_id)
    stage = pipeline_service.get_stage(db, ctx, opp.stage_id)
    return _opportunity_item(opp, stage.name)


class WorkflowRef(_In):
    run_id: uuid.UUID


class WorkflowStatusOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    current_step: str | None
    error_category: str | None


def _workflow_out(run: Any) -> WorkflowStatusOut:
    return WorkflowStatusOut(
        id=run.id,
        kind=run.kind.value,
        status=run.status.value,
        current_step=run.current_step,
        error_category=run.error_category,
    )


def get_workflow_status(db: Session, ctx: OrgContext, args: WorkflowRef) -> WorkflowStatusOut:
    return _workflow_out(workflow_service.get_run(db, ctx, args.run_id))


def request_action_approval(db: Session, ctx: OrgContext, args: LeadRef) -> WorkflowStatusOut:
    """The only route to a lead status change here: a server-side run a person must approve.
    A caller can ask for this, but cannot answer it."""
    return _workflow_out(
        workflow_service.enqueue(
            db, ctx, args.lead_id, WorkflowKind.lead_intelligence, propose_status=True
        )
    )


def _spec(
    name: str, handler: Any, input_model: type[BaseModel], output_model: type[BaseModel], **kw: Any
) -> ToolSpec:
    description = (handler.__doc__ or "").strip() or kw.pop("description", name)
    kw.pop("description", None)
    return ToolSpec(
        name=name,
        description=description,
        input_model=input_model,
        output_model=output_model,
        handler=handler,
        **kw,
    )


_LEAD = {"lead_field": "lead_id", "audit_fields": ("lead_id",)}

CATALOG: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        _spec(
            "search_leads",
            search_leads,
            SearchLeadsIn,
            SearchLeadsOut,
            description="Find leads by name, email, or company.",
            permission=Permission.leads_read,
            side_effect="read",
        ),
        _spec(
            "get_lead_profile",
            get_lead_profile,
            LeadRef,
            LeadProfile,
            description="Read one lead's contact details and company facts.",
            permission=Permission.leads_read,
            side_effect="read",
            sources=_profile_sources,
            **_LEAD,
        ),
        _spec(
            "create_lead",
            create_lead,
            CreateLeadIn,
            LeadProfile,
            description="Create a lead. Refused if the email already exists.",
            permission=Permission.leads_write,
            side_effect="write",
        ),
        _spec(
            "update_lead",
            update_lead,
            UpdateLeadIn,
            LeadProfile,
            permission=Permission.leads_write,
            side_effect="write",
            **_LEAD,
        ),
        _spec(
            "list_lead_activities",
            list_lead_activities,
            ListActivitiesIn,
            ActivitiesOut,
            description="Read a lead's recent timeline, newest first.",
            permission=Permission.leads_read,
            side_effect="read",
            **_LEAD,
        ),
        _spec(
            "get_research_evidence",
            get_research_evidence,
            LeadRef,
            EvidenceListOut,
            description="Read the accepted research evidence for one lead.",
            permission=Permission.intelligence_read,
            side_effect="read",
            sources=_evidence_sources,
            **_LEAD,
        ),
        _spec(
            "search_company_research",
            search_company_research,
            SearchResearchIn,
            EvidenceListOut,
            description="Search accepted research evidence by keyword, optionally for one lead.",
            permission=Permission.intelligence_read,
            side_effect="read",
            sources=_evidence_sources,
            **_LEAD,
        ),
        _spec(
            "save_research_evidence",
            save_research_evidence,
            SaveEvidenceIn,
            SavedEvidence,
            permission=Permission.research_write,
            side_effect="write",
            limit_key="evidence",
            limit_per_minute=60,
            **_LEAD,
        ),
        _spec(
            "get_lead_score",
            get_lead_score,
            LeadRef,
            ScoreOut,
            description="Read a lead's latest score and the reasons behind it.",
            permission=Permission.intelligence_read,
            side_effect="read",
            sources=_score_sources,
            **_LEAD,
        ),
        _spec(
            "evaluate_lead_fit",
            evaluate_lead_fit,
            LeadRef,
            ScoreOut,
            description="Score a lead now against the ICP, by fixed rules. Adds an assessment.",
            permission=Permission.assessments_run,
            side_effect="write",
            limit_key="assess",
            limit_per_minute=30,
            **_LEAD,
        ),
        _spec(
            "get_icp_configuration",
            get_icp_configuration,
            NoInput,
            IcpOut,
            description="Read the active ideal customer profile.",
            permission=Permission.intelligence_read,
            side_effect="read",
            sources=_icp_sources,
        ),
        _spec(
            "get_pipeline_summary",
            get_pipeline_summary,
            NoInput,
            PipelineOut,
            description="Read the count and per-currency totals in each pipeline stage.",
            permission=Permission.pipeline_read,
            side_effect="read",
            sources=_pipeline_sources,
        ),
        _spec(
            "list_open_opportunities",
            list_open_opportunities,
            ListOpportunitiesIn,
            OpportunitiesOut,
            permission=Permission.pipeline_read,
            side_effect="read",
            sources=_opportunity_sources,
        ),
        _spec(
            "get_opportunity_details",
            get_opportunity_details,
            OpportunityRef,
            OpportunityItem,
            description="Read one opportunity.",
            permission=Permission.pipeline_read,
            side_effect="read",
            audit_fields=("opportunity_id",),
        ),
        _spec(
            "get_workflow_status",
            get_workflow_status,
            WorkflowRef,
            WorkflowStatusOut,
            description="Read the status of a workflow run.",
            permission=Permission.workflows_read,
            side_effect="read",
            audit_fields=("run_id",),
        ),
        _spec(
            "request_action_approval",
            request_action_approval,
            LeadRef,
            WorkflowStatusOut,
            permission=Permission.workflows_run,
            side_effect="write",
            limit_key="workflow",
            limit_per_minute=10,
            **_LEAD,
        ),
    )
}
