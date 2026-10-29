"""Pipeline stages, opportunities, and analytics (all org-scoped)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import DbDep, OrgContext, require
from app.core.permissions import Permission
from app.schemas.crm import (
    OpportunityCreate,
    OpportunityOut,
    OpportunityUpdate,
    OverviewOut,
    PipelineSummaryOut,
    StageCreate,
    StageOut,
    StageUpdate,
)
from app.services import pipeline_service

router = APIRouter(prefix="/organizations/{org_id}", tags=["pipeline"])

PipelineRead = Annotated[OrgContext, Depends(require(Permission.pipeline_read))]
PipelineWrite = Annotated[OrgContext, Depends(require(Permission.pipeline_write))]
PipelineConfigure = Annotated[OrgContext, Depends(require(Permission.pipeline_configure))]


@router.get("/pipeline/stages", response_model=list[StageOut])
def list_stages(ctx: PipelineRead, db: DbDep) -> list[StageOut]:
    return [StageOut.model_validate(s) for s in pipeline_service.list_stages(db, ctx)]


@router.post("/pipeline/stages", status_code=201, response_model=StageOut)
def create_stage(body: StageCreate, ctx: PipelineConfigure, db: DbDep) -> StageOut:
    out = StageOut.model_validate(pipeline_service.create_stage(db, ctx, body.name, body.kind))
    db.commit()
    return out


@router.patch("/pipeline/stages/{stage_id}", response_model=StageOut)
def rename_stage(
    stage_id: uuid.UUID, body: StageUpdate, ctx: PipelineConfigure, db: DbDep
) -> StageOut:
    out = StageOut.model_validate(pipeline_service.rename_stage(db, ctx, stage_id, body.name))
    db.commit()
    return out


@router.get("/pipeline/summary", response_model=PipelineSummaryOut)
def pipeline_summary(ctx: PipelineRead, db: DbDep) -> PipelineSummaryOut:
    return PipelineSummaryOut(stages=pipeline_service.pipeline_summary(db, ctx))


@router.get("/opportunities", response_model=list[OpportunityOut])
def list_opportunities(
    ctx: PipelineRead,
    db: DbDep,
    stage_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    include_closed: bool = False,
) -> list[OpportunityOut]:
    return [
        OpportunityOut.model_validate(o)
        for o in pipeline_service.list_opportunities(
            db, ctx, stage_id=stage_id, owner_id=owner_id, include_closed=include_closed
        )
    ]


@router.post("/opportunities", status_code=201, response_model=OpportunityOut)
def create_opportunity(body: OpportunityCreate, ctx: PipelineWrite, db: DbDep) -> OpportunityOut:
    out = OpportunityOut.model_validate(pipeline_service.create_opportunity(db, ctx, body))
    db.commit()
    return out


@router.get("/opportunities/{opp_id}", response_model=OpportunityOut)
def get_opportunity(opp_id: uuid.UUID, ctx: PipelineRead, db: DbDep) -> OpportunityOut:
    return OpportunityOut.model_validate(pipeline_service.get_opportunity(db, ctx, opp_id))


@router.patch("/opportunities/{opp_id}", response_model=OpportunityOut)
def update_opportunity(
    opp_id: uuid.UUID, body: OpportunityUpdate, ctx: PipelineWrite, db: DbDep
) -> OpportunityOut:
    out = OpportunityOut.model_validate(pipeline_service.update_opportunity(db, ctx, opp_id, body))
    db.commit()
    return out


@router.get("/analytics/overview", response_model=OverviewOut)
def analytics_overview(ctx: PipelineRead, db: DbDep) -> OverviewOut:
    return pipeline_service.overview(db, ctx)
