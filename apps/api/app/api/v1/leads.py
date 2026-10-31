"""Lead, company, CSV import, and export endpoints (all org-scoped)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select

from app.core.auth import DbDep, OrgContext, require
from app.core.errors import ForbiddenError, NotFoundError
from app.core.permissions import Permission, has_permission
from app.core.rate_limit import get_rate_limiter
from app.models import ImportStatus, LeadImport, LeadStatus
from app.schemas.crm import (
    ActivityOut,
    BulkIn,
    BulkOut,
    CompanyDetailOut,
    CompanyIn,
    CompanyOut,
    CompanyPage,
    CompanyUpdate,
    ImportIn,
    ImportOut,
    ImportPreviewIn,
    ImportPreviewOut,
    LeadCreate,
    LeadOut,
    LeadPage,
    LeadUpdate,
    NoteIn,
    OpportunityOut,
)
from app.services import audit, csv_service, lead_service
from app.services.lead_service import LeadFilters

IMPORTS_PER_MINUTE = 20

router = APIRouter(prefix="/organizations/{org_id}", tags=["leads"])

LeadsRead = Annotated[OrgContext, Depends(require(Permission.leads_read))]
LeadsWrite = Annotated[OrgContext, Depends(require(Permission.leads_write))]
LeadsDelete = Annotated[OrgContext, Depends(require(Permission.leads_delete))]
LeadsImport = Annotated[OrgContext, Depends(require(Permission.leads_import))]
LeadsExport = Annotated[OrgContext, Depends(require(Permission.leads_export))]
MAX_EXPORT_ROWS = 50_000


class LeadDetailOut(LeadOut):
    activities: list[ActivityOut]
    opportunities: list[OpportunityOut]


def _filters(
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: Annotated[list[LeadStatus] | None, Query()] = None,
    owner: Annotated[str | None, Query(max_length=40, description="User id or 'none'")] = None,
    tag: Annotated[str | None, Query(max_length=50)] = None,
    company_id: uuid.UUID | None = None,
    source: Annotated[str | None, Query(max_length=80)] = None,
    import_id: uuid.UUID | None = None,
    fit: Literal["high", "medium", "low", "none"] | None = None,
) -> LeadFilters:
    return LeadFilters(
        q=q or None,
        statuses=tuple(status or ()),
        owner=owner,
        tag=tag,
        company_id=company_id,
        source=source,
        import_id=import_id,
        fit=fit,
    )


FiltersDep = Annotated[LeadFilters, Depends(_filters)]


# --- leads ------------------------------------------------------------------------------


@router.get("/leads", response_model=LeadPage)
def list_leads(
    ctx: LeadsRead,
    db: DbDep,
    filters: FiltersDep,
    sort: Annotated[str, Query(max_length=20)] = "-created_at",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> LeadPage:
    rows, next_cursor, total = lead_service.list_leads(
        db, ctx, filters, sort=sort, limit=limit, cursor=cursor
    )
    scores = lead_service.latest_scores(db, [lead.id for lead, _ in rows])
    items = []
    for lead, company in rows:
        score, fit = scores.get(lead.id, (None, None))
        items.append(
            lead_service.to_out(lead, company).model_copy(update={"score": score, "fit": fit})
        )
    return LeadPage(
        items=items,
        next_cursor=next_cursor,
        total=total,
    )


@router.post("/leads", status_code=201, response_model=LeadOut)
def create_lead(body: LeadCreate, ctx: LeadsWrite, db: DbDep) -> LeadOut:
    lead = lead_service.create_lead(db, ctx, body)
    out = lead_service.to_out(*lead_service.lead_with_company(db, ctx, lead.id))
    db.commit()
    return out


@router.get("/leads/export", response_class=Response)
def export_leads(ctx: LeadsExport, db: DbDep, filters: FiltersDep) -> Response:
    rows = lead_service.iter_export(db, ctx, filters)
    if len(rows) > MAX_EXPORT_ROWS:
        raise ForbiddenError(
            f"Exports are limited to {MAX_EXPORT_ROWS:,} leads; narrow the filters",
            code="export_too_large",
        )
    body = csv_service.export_csv(rows)
    audit.record(
        db,
        "leads.exported",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="lead",
        data={"count": len(rows)},
    )
    db.commit()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"content-disposition": f'attachment; filename="leads-{stamp}.csv"'},
    )


@router.post("/leads/bulk", response_model=BulkOut)
def bulk_leads(body: BulkIn, ctx: LeadsWrite, db: DbDep) -> BulkOut:
    if body.action == "delete" and not has_permission(ctx.role, Permission.leads_delete):
        raise ForbiddenError("Your role does not allow leads:delete")
    affected = lead_service.bulk_update(db, ctx, body)
    db.commit()
    return BulkOut(affected=affected)


@router.get("/leads/{lead_id}", response_model=LeadDetailOut)
def get_lead(lead_id: uuid.UUID, ctx: LeadsRead, db: DbDep) -> LeadDetailOut:
    lead, company = lead_service.lead_with_company(db, ctx, lead_id)
    activities, opportunities = lead_service.lead_timeline(db, ctx, lead_id)
    return LeadDetailOut(
        **lead_service.to_out(lead, company).model_dump(),
        activities=[ActivityOut.model_validate(a) for a in activities],
        opportunities=[OpportunityOut.model_validate(o) for o in opportunities],
    )


@router.patch("/leads/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: uuid.UUID, body: LeadUpdate, ctx: LeadsWrite, db: DbDep) -> LeadOut:
    lead_service.update_lead(db, ctx, lead_id, body)
    out = lead_service.to_out(*lead_service.lead_with_company(db, ctx, lead_id))
    db.commit()
    return out


@router.delete("/leads/{lead_id}", status_code=204)
def delete_lead(lead_id: uuid.UUID, ctx: LeadsDelete, db: DbDep) -> Response:
    lead_service.get_lead(db, ctx, lead_id)
    lead_service.soft_delete(db, ctx, [lead_id])
    db.commit()
    return Response(status_code=204)


@router.post("/leads/{lead_id}/notes", status_code=201, response_model=list[ActivityOut])
def add_note(lead_id: uuid.UUID, body: NoteIn, ctx: LeadsWrite, db: DbDep) -> list[ActivityOut]:
    lead_service.add_note(db, ctx, lead_id, body.body)
    db.flush()
    activities, _ = lead_service.lead_timeline(db, ctx, lead_id)
    out = [ActivityOut.model_validate(a) for a in activities]
    db.commit()
    return out


# --- imports ----------------------------------------------------------------------------


@router.post("/lead-imports/preview", response_model=ImportPreviewOut)
def preview_import(body: ImportPreviewIn, ctx: LeadsImport) -> ImportPreviewOut:
    headers, sample, total = csv_service.preview(body.content)
    return ImportPreviewOut(
        headers=headers,
        sample_rows=sample,
        total_rows=total,
        suggested_mapping=csv_service.suggest_mapping(headers),
    )


@router.post("/lead-imports", response_model=ImportOut)
def run_import(body: ImportIn, ctx: LeadsImport, db: DbDep, response: Response) -> ImportOut:
    get_rate_limiter().hit(f"import:{ctx.org_id}", IMPORTS_PER_MINUTE)
    record, replayed = csv_service.run_import(db, ctx, body)
    out = ImportOut.model_validate(record).model_copy(update={"replayed": replayed})
    db.commit()
    if record.status in (ImportStatus.queued, ImportStatus.running):
        response.status_code = 202
    else:
        response.status_code = 200 if replayed else 201
    return out


@router.get("/lead-imports/{import_id}", response_model=ImportOut)
def get_import(import_id: uuid.UUID, ctx: LeadsRead, db: DbDep) -> ImportOut:
    record = db.scalar(
        select(LeadImport).where(
            LeadImport.id == import_id, LeadImport.organization_id == ctx.org_id
        )
    )
    if record is None:
        raise NotFoundError("Import not found")
    return ImportOut.model_validate(record)


# --- companies --------------------------------------------------------------------------


@router.get("/companies", response_model=CompanyPage)
def list_companies(
    ctx: LeadsRead,
    db: DbDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> CompanyPage:
    items, next_cursor = lead_service.list_companies(db, ctx, q=q, limit=limit, cursor=cursor)
    return CompanyPage(items=[CompanyOut.model_validate(c) for c in items], next_cursor=next_cursor)


@router.post("/companies", status_code=201, response_model=CompanyOut)
def create_company(body: CompanyIn, ctx: LeadsWrite, db: DbDep) -> CompanyOut:
    out = CompanyOut.model_validate(lead_service.create_company(db, ctx, body))
    db.commit()
    return out


@router.get("/companies/{company_id}", response_model=CompanyDetailOut)
def get_company(company_id: uuid.UUID, ctx: LeadsRead, db: DbDep) -> CompanyDetailOut:
    company = lead_service.get_company(db, ctx, company_id)
    return CompanyDetailOut(
        **CompanyOut.model_validate(company).model_dump(),
        lead_count=lead_service.company_lead_count(db, ctx, company_id),
    )


@router.patch("/companies/{company_id}", response_model=CompanyOut)
def update_company(
    company_id: uuid.UUID, body: CompanyUpdate, ctx: LeadsWrite, db: DbDep
) -> CompanyOut:
    out = CompanyOut.model_validate(lead_service.update_company(db, ctx, company_id, body))
    db.commit()
    return out
