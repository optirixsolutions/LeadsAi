"""Analytics from stored records (org-scoped)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.core.auth import DbDep, OrgContext, require
from app.core.permissions import Permission
from app.schemas.analytics import AnalyticsReport, Attention
from app.services import analytics_service

router = APIRouter(prefix="/organizations/{org_id}", tags=["analytics"])

Read = Annotated[OrgContext, Depends(require(Permission.analytics_read))]


@router.get("/analytics/report", response_model=AnalyticsReport)
def report(
    ctx: Read,
    db: DbDep,
    days: Annotated[Literal["7", "30", "90"], Query()] = "30",
) -> AnalyticsReport:
    return analytics_service.report(db, ctx, int(days))


@router.get("/analytics/attention", response_model=Attention)
def attention(ctx: Read, db: DbDep) -> Attention:
    return analytics_service.attention(db, ctx)
