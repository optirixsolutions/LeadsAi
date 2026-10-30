"""ICP configuration, research evidence, assessments, and research briefs (all org-scoped)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import DbDep, OrgContext, require
from app.core.errors import NotFoundError
from app.core.permissions import Permission, has_permission
from app.core.rate_limit import get_rate_limiter
from app.models import ResearchBrief
from app.schemas.intelligence import (
    AssessmentDetail,
    AssessmentOut,
    AssessmentReview,
    BriefOut,
    EvidenceCreate,
    EvidenceFetch,
    EvidenceOut,
    EvidenceReview,
    IcpCreate,
    IcpOut,
)
from app.services import brief_service, intelligence_service

router = APIRouter(prefix="/organizations/{org_id}", tags=["intelligence"])

Read = Annotated[OrgContext, Depends(require(Permission.intelligence_read))]
Research = Annotated[OrgContext, Depends(require(Permission.research_write))]
Assess = Annotated[OrgContext, Depends(require(Permission.assessments_run))]
Review = Annotated[OrgContext, Depends(require(Permission.intelligence_review))]
Configure = Annotated[OrgContext, Depends(require(Permission.icp_configure))]

# Per organization: a fetch can hold one of 10 shared connections for its whole deadline.
FETCHES_PER_MINUTE = 10
BRIEFS_PER_MINUTE = 10
# Per user: each write adds rows that are kept, and screening reads the whole text.
EVIDENCE_PER_MINUTE = 60
ASSESSMENTS_PER_MINUTE = 30


@router.get("/icp", response_model=IcpOut | None)
def get_icp(ctx: Read, db: DbDep) -> IcpOut | None:
    icp = intelligence_service.active_icp(db, ctx)
    return IcpOut.model_validate(icp) if icp else None


@router.get("/icp/versions", response_model=list[IcpOut])
def list_icp_versions(ctx: Read, db: DbDep) -> list[IcpOut]:
    return [IcpOut.model_validate(i) for i in intelligence_service.list_icp_versions(db, ctx)]


@router.post("/icp", status_code=201, response_model=IcpOut)
def create_icp_version(body: IcpCreate, ctx: Configure, db: DbDep) -> IcpOut:
    out = IcpOut.model_validate(intelligence_service.create_icp(db, ctx, body))
    db.commit()
    return out


@router.get("/leads/{lead_id}/evidence", response_model=list[EvidenceOut])
def list_evidence(lead_id: uuid.UUID, ctx: Read, db: DbDep) -> list[EvidenceOut]:
    return [
        EvidenceOut.model_validate(e) for e in intelligence_service.list_evidence(db, ctx, lead_id)
    ]


@router.post("/leads/{lead_id}/evidence", status_code=201, response_model=EvidenceOut)
def add_evidence(lead_id: uuid.UUID, body: EvidenceCreate, ctx: Research, db: DbDep) -> EvidenceOut:
    get_rate_limiter().hit(f"evidence:{ctx.org_id}:{ctx.user_id}", EVIDENCE_PER_MINUTE)
    out = EvidenceOut.model_validate(intelligence_service.add_evidence(db, ctx, lead_id, body))
    db.commit()
    return out


@router.post("/leads/{lead_id}/evidence/fetch", status_code=201, response_model=EvidenceOut)
def fetch_evidence(
    lead_id: uuid.UUID, body: EvidenceFetch, ctx: Research, db: DbDep
) -> EvidenceOut:
    get_rate_limiter().hit(f"evidence-fetch:{ctx.org_id}", FETCHES_PER_MINUTE)
    out = EvidenceOut.model_validate(
        intelligence_service.fetch_evidence(db, ctx, lead_id, body.url)
    )
    db.commit()
    return out


@router.patch("/leads/{lead_id}/evidence/{evidence_id}", response_model=EvidenceOut)
def review_evidence(
    lead_id: uuid.UUID, evidence_id: uuid.UUID, body: EvidenceReview, ctx: Review, db: DbDep
) -> EvidenceOut:
    out = EvidenceOut.model_validate(
        intelligence_service.review_evidence(db, ctx, lead_id, evidence_id, body.status)
    )
    db.commit()
    return out


def _detail(db: DbDep, ctx: OrgContext, assessment: object) -> AssessmentDetail:
    base = AssessmentOut.model_validate(assessment)
    evidence = intelligence_service.assessment_evidence(db, ctx, assessment)  # type: ignore[arg-type]
    return AssessmentDetail(
        **base.model_dump(), evidence=[EvidenceOut.model_validate(e) for e in evidence]
    )


@router.post("/leads/{lead_id}/assessments", status_code=201, response_model=AssessmentDetail)
def assess_lead(lead_id: uuid.UUID, ctx: Assess, db: DbDep) -> AssessmentDetail:
    get_rate_limiter().hit(f"assess:{ctx.org_id}:{ctx.user_id}", ASSESSMENTS_PER_MINUTE)
    out = _detail(db, ctx, intelligence_service.assess_lead(db, ctx, lead_id))
    db.commit()
    return out


@router.get("/leads/{lead_id}/assessments", response_model=list[AssessmentOut])
def list_assessments(lead_id: uuid.UUID, ctx: Read, db: DbDep) -> list[AssessmentOut]:
    return [
        AssessmentOut.model_validate(a)
        for a in intelligence_service.list_assessments(db, ctx, lead_id)
    ]


@router.get("/assessments/{assessment_id}", response_model=AssessmentDetail)
def get_assessment(assessment_id: uuid.UUID, ctx: Read, db: DbDep) -> AssessmentDetail:
    return _detail(db, ctx, intelligence_service.get_assessment(db, ctx, assessment_id))


@router.patch("/assessments/{assessment_id}", response_model=AssessmentOut)
def review_assessment(
    assessment_id: uuid.UUID, body: AssessmentReview, ctx: Review, db: DbDep
) -> AssessmentOut:
    out = AssessmentOut.model_validate(
        intelligence_service.review_assessment(db, ctx, assessment_id, body.evaluation_status)
    )
    db.commit()
    return out


def _brief_out(brief: ResearchBrief, ctx: OrgContext) -> BriefOut:
    out = BriefOut.model_validate(brief)
    if not has_permission(ctx.role, Permission.intelligence_review):
        for claim in out.rejected_claims:
            claim.text = None
    return out


@router.post("/leads/{lead_id}/briefs", status_code=202, response_model=BriefOut)
def request_brief(lead_id: uuid.UUID, ctx: Research, db: DbDep) -> BriefOut:
    get_rate_limiter().hit(f"brief:{ctx.org_id}", BRIEFS_PER_MINUTE)
    brief = brief_service.create_brief(db, ctx, lead_id)
    out = _brief_out(brief, ctx)
    db.commit()
    return out


@router.get("/leads/{lead_id}/briefs/latest", response_model=BriefOut)
def latest_brief(lead_id: uuid.UUID, ctx: Read, db: DbDep) -> BriefOut:
    brief = brief_service.latest_brief(db, ctx, lead_id)
    if brief is None:
        raise NotFoundError("No brief yet")
    out = _brief_out(brief, ctx)
    db.commit()
    return out
