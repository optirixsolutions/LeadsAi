"""Leads, companies, and activity timeline.

All functions take an `OrgContext` and filter explicitly by `ctx.org_id`; RLS is the backstop.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, String, cast, func, or_, select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import OrgContext
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.pagination import decode_cursor, encode_cursor
from app.models import Activity, ActivityType, Company, Lead, LeadStatus, Membership, Opportunity
from app.schemas.crm import (
    BulkIn,
    CompanyIn,
    CompanySummary,
    CompanyUpdate,
    LeadCreate,
    LeadOut,
    LeadUpdate,
)
from app.services import audit
from app.services.normalize import normalize_domain

ACTIVITY_LIMIT = 50


class InvalidReferenceError(AppError):
    status_code = 422
    code = "invalid_reference"


def _now() -> datetime:
    return datetime.now(UTC)


# --- shared helpers ---------------------------------------------------------------------


def record_activity(
    db: Session,
    ctx: OrgContext,
    type_: ActivityType,
    *,
    lead_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
    body: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    db.add(
        Activity(
            organization_id=ctx.org_id,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            actor_user_id=ctx.user_id,
            type=type_,
            body=body,
            data=data or {},
        )
    )


def ensure_member(db: Session, ctx: OrgContext, user_id: uuid.UUID | None) -> None:
    """Assignees must belong to the org; otherwise a user ID from elsewhere could be planted."""
    if user_id is None:
        return
    found = db.scalar(
        select(Membership.id).where(
            Membership.organization_id == ctx.org_id, Membership.user_id == user_id
        )
    )
    if found is None:
        raise InvalidReferenceError("Owner must be a member of this organization")


def get_company(db: Session, ctx: OrgContext, company_id: uuid.UUID) -> Company:
    company = db.scalar(
        select(Company).where(Company.id == company_id, Company.organization_id == ctx.org_id)
    )
    if company is None:
        raise NotFoundError("Company not found")
    return company


def company_ref(db: Session, ctx: OrgContext, company_id: uuid.UUID) -> Company:
    try:
        return get_company(db, ctx, company_id)
    except NotFoundError as exc:
        raise InvalidReferenceError("Company does not exist in this organization") from exc


def find_or_create_company(
    db: Session, ctx: OrgContext, *, name: str | None, domain: str | None
) -> Company | None:
    """Match by normalized domain first, then by case-insensitive name; create if neither."""
    domain = normalize_domain(domain)
    if domain:
        found = db.scalar(
            select(Company).where(Company.organization_id == ctx.org_id, Company.domain == domain)
        )
        if found:
            return found
    if name:
        found = db.scalar(
            select(Company)
            .where(Company.organization_id == ctx.org_id, func.lower(Company.name) == name.lower())
            .order_by(Company.created_at)
            .limit(1)
        )
        if found:
            if domain and not found.domain:
                found.domain = domain
            return found
    if not (name or domain):
        return None
    company = Company(organization_id=ctx.org_id, name=name or domain or "", domain=domain)
    db.add(company)
    db.flush()
    return company


def to_out(lead: Lead, company: Company | None) -> LeadOut:
    return LeadOut(
        id=lead.id,
        first_name=lead.first_name,
        last_name=lead.last_name,
        email=lead.email,
        title=lead.title,
        phone=lead.phone,
        linkedin_url=lead.linkedin_url,
        source=lead.source,
        status=lead.status,
        tags=list(lead.tags),
        custom_fields=dict(lead.custom_fields),
        company=CompanySummary(id=company.id, name=company.name, domain=company.domain)
        if company
        else None,
        owner_user_id=lead.owner_user_id,
        import_id=lead.import_id,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


# --- companies --------------------------------------------------------------------------


def create_company(db: Session, ctx: OrgContext, body: CompanyIn) -> Company:
    company = Company(
        organization_id=ctx.org_id,
        name=body.name,
        domain=normalize_domain(body.domain),
        industry=body.industry,
        employee_count=body.employee_count,
        country=body.country,
    )
    db.add(company)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("A company with this domain already exists") from exc
    return company


def update_company(
    db: Session, ctx: OrgContext, company_id: uuid.UUID, body: CompanyUpdate
) -> Company:
    company = get_company(db, ctx, company_id)
    changes = body.model_dump(exclude_unset=True)
    if "domain" in changes:
        changes["domain"] = normalize_domain(changes["domain"])
    for key, value in changes.items():
        setattr(company, key, value)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("A company with this domain already exists") from exc
    return company


def list_companies(
    db: Session, ctx: OrgContext, *, q: str | None, limit: int, cursor: str | None
) -> tuple[list[Company], str | None]:
    stmt = select(Company).where(Company.organization_id == ctx.org_id)
    if q:
        pattern = f"%{_escape_like(q)}%"
        stmt = stmt.where(
            or_(
                Company.name.ilike(pattern, escape="\\"), Company.domain.ilike(pattern, escape="\\")
            )
        )
    key = func.lower(Company.name)
    if cursor:
        value, ident = decode_cursor(cursor)
        stmt = stmt.where(tuple_(key, Company.id) > tuple_(str(value), ident))
    rows = list(db.scalars(stmt.order_by(key, Company.id).limit(limit + 1)))
    nxt = (
        encode_cursor(rows[limit - 1].name.lower(), rows[limit - 1].id)
        if len(rows) > limit
        else None
    )
    return rows[:limit], nxt


def company_lead_count(db: Session, ctx: OrgContext, company_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Lead)
            .where(
                Lead.organization_id == ctx.org_id,
                Lead.company_id == company_id,
                Lead.deleted_at.is_(None),
            )
        )
        or 0
    )


# --- lead queries -----------------------------------------------------------------------


@dataclass(frozen=True)
class LeadFilters:
    q: str | None = None
    statuses: tuple[LeadStatus, ...] = ()
    owner: str | None = None  # a user id, or "none" for unassigned
    tag: str | None = None
    company_id: uuid.UUID | None = None
    source: str | None = None
    import_id: uuid.UUID | None = None


SORTS = {"created_at", "updated_at", "last_name", "email"}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtered(ctx: OrgContext, f: LeadFilters) -> Select[Lead, Company]:
    stmt = (
        select(Lead, Company)
        .outerjoin(Company, Company.id == Lead.company_id)
        .where(Lead.organization_id == ctx.org_id, Lead.deleted_at.is_(None))
    )
    if f.q:
        pattern = f"%{_escape_like(f.q.strip())}%"
        full_name = func.concat_ws(" ", Lead.first_name, Lead.last_name)
        stmt = stmt.where(
            or_(
                full_name.ilike(pattern, escape="\\"),
                Lead.email.ilike(pattern, escape="\\"),
                Company.name.ilike(pattern, escape="\\"),
                Lead.title.ilike(pattern, escape="\\"),
            )
        )
    if f.statuses:
        stmt = stmt.where(Lead.status.in_(f.statuses))
    if f.owner == "none":
        stmt = stmt.where(Lead.owner_user_id.is_(None))
    elif f.owner:
        try:
            stmt = stmt.where(Lead.owner_user_id == uuid.UUID(f.owner))
        except ValueError as exc:
            raise AppError("owner must be a user id or 'none'", code="invalid_filter") from exc
    if f.tag:
        stmt = stmt.where(Lead.tags.contains([f.tag.strip().lower()]))
    if f.company_id:
        stmt = stmt.where(Lead.company_id == f.company_id)
    if f.source:
        stmt = stmt.where(Lead.source == f.source)
    if f.import_id:
        stmt = stmt.where(Lead.import_id == f.import_id)
    return stmt


def list_leads(
    db: Session,
    ctx: OrgContext,
    filters: LeadFilters,
    *,
    sort: str,
    limit: int,
    cursor: str | None,
) -> tuple[list[tuple[Lead, Company | None]], str | None, int]:
    descending = sort.startswith("-")
    field = sort.lstrip("-")
    if field not in SORTS:
        raise AppError(f"sort must be one of {sorted(SORTS)}", code="invalid_sort")

    base = _filtered(ctx, filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    column = getattr(Lead, field)
    is_text = field in ("last_name", "email")
    key = func.coalesce(func.lower(cast(column, String)), "") if is_text else column
    stmt = base
    if cursor:
        value, ident = decode_cursor(cursor)
        if not is_text:
            value = datetime.fromisoformat(str(value))
        cmp = (
            tuple_(key, Lead.id) < tuple_(value, ident)
            if descending
            else (tuple_(key, Lead.id) > tuple_(value, ident))
        )
        stmt = stmt.where(cmp)
    order = (key.desc(), Lead.id.desc()) if descending else (key.asc(), Lead.id.asc())
    rows: list[tuple[Lead, Company | None]] = [
        (lead, company) for lead, company in db.execute(stmt.order_by(*order).limit(limit + 1))
    ]

    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1][0]
        raw = getattr(last, field)
        value = (raw or "").lower() if is_text else raw.isoformat()
        next_cursor = encode_cursor(value, last.id)
    return rows[:limit], next_cursor, total


def iter_export(
    db: Session, ctx: OrgContext, filters: LeadFilters
) -> list[tuple[Lead, Company | None]]:
    stmt = _filtered(ctx, filters).order_by(Lead.created_at, Lead.id)
    return [(lead, company) for lead, company in db.execute(stmt)]


def get_lead(db: Session, ctx: OrgContext, lead_id: uuid.UUID) -> Lead:
    lead = db.scalar(
        select(Lead).where(
            Lead.id == lead_id, Lead.organization_id == ctx.org_id, Lead.deleted_at.is_(None)
        )
    )
    if lead is None:
        raise NotFoundError("Lead not found")
    return lead


def lead_with_company(
    db: Session, ctx: OrgContext, lead_id: uuid.UUID
) -> tuple[Lead, Company | None]:
    lead = get_lead(db, ctx, lead_id)
    company = get_company(db, ctx, lead.company_id) if lead.company_id else None
    return lead, company


def lead_timeline(
    db: Session, ctx: OrgContext, lead_id: uuid.UUID
) -> tuple[list[Activity], list[Opportunity]]:
    activities = list(
        db.scalars(
            select(Activity)
            .where(Activity.organization_id == ctx.org_id, Activity.lead_id == lead_id)
            .order_by(Activity.created_at.desc(), Activity.id.desc())
            .limit(ACTIVITY_LIMIT)
        )
    )
    opportunities = list(
        db.scalars(
            select(Opportunity)
            .where(Opportunity.organization_id == ctx.org_id, Opportunity.lead_id == lead_id)
            .order_by(Opportunity.created_at.desc())
        )
    )
    return activities, opportunities


def find_duplicate(
    db: Session, ctx: OrgContext, email: str | None, *, exclude: uuid.UUID | None = None
) -> Lead | None:
    if not email:
        return None
    stmt = select(Lead).where(
        Lead.organization_id == ctx.org_id, Lead.email == email, Lead.deleted_at.is_(None)
    )
    if exclude:
        stmt = stmt.where(Lead.id != exclude)
    return db.scalar(stmt)


def _duplicate_error(existing: Lead) -> ConflictError:
    return ConflictError(
        "A lead with this email already exists",
        code="duplicate_lead",
        details={"existing_lead_id": str(existing.id)},
    )


# --- lead mutations ---------------------------------------------------------------------


def _resolve_company(
    db: Session, ctx: OrgContext, body: LeadCreate | LeadUpdate
) -> uuid.UUID | None:
    if body.company_id:
        return company_ref(db, ctx, body.company_id).id
    if body.company_name:
        company = find_or_create_company(db, ctx, name=body.company_name, domain=None)
        return company.id if company else None
    return None


def create_lead(db: Session, ctx: OrgContext, body: LeadCreate) -> Lead:
    if existing := find_duplicate(db, ctx, body.email):
        raise _duplicate_error(existing)
    ensure_member(db, ctx, body.owner_user_id)
    lead = Lead(
        organization_id=ctx.org_id,
        company_id=_resolve_company(db, ctx, body),
        owner_user_id=body.owner_user_id,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        title=body.title,
        phone=body.phone,
        linkedin_url=body.linkedin_url,
        source=body.source or "manual",
        status=body.status or LeadStatus.new,
        tags=body.tags or [],
        custom_fields=body.custom_fields or {},
    )
    db.add(lead)
    try:
        db.flush()
    except IntegrityError as exc:  # concurrent create with the same email
        raise ConflictError("A lead with this email already exists", code="duplicate_lead") from exc
    record_activity(db, ctx, ActivityType.created, lead_id=lead.id)
    return lead


_PLAIN_FIELDS = (
    "first_name",
    "last_name",
    "email",
    "title",
    "phone",
    "linkedin_url",
    "source",
    "tags",
    "custom_fields",
)


def update_lead(db: Session, ctx: OrgContext, lead_id: uuid.UUID, body: LeadUpdate) -> Lead:
    lead = get_lead(db, ctx, lead_id)
    sent = body.model_fields_set

    if (
        "email" in sent
        and body.email != lead.email
        and (existing := find_duplicate(db, ctx, body.email, exclude=lead.id))
    ):
        raise _duplicate_error(existing)

    changed: dict[str, Any] = {}
    for name in _PLAIN_FIELDS:
        if name in sent:
            new = getattr(body, name)
            if name in ("tags", "custom_fields") and new is None:
                new = [] if name == "tags" else {}
            if getattr(lead, name) != new:
                changed[name] = new
                setattr(lead, name, new)

    if "company_id" in sent or "company_name" in sent:
        company_id = _resolve_company(db, ctx, body)
        if company_id != lead.company_id:
            changed["company_id"] = str(company_id) if company_id else None
            lead.company_id = company_id

    if "status" in sent and body.status and body.status != lead.status:
        record_activity(
            db,
            ctx,
            ActivityType.status_changed,
            lead_id=lead.id,
            data={"from": lead.status.value, "to": body.status.value},
        )
        lead.status = body.status

    if "owner_user_id" in sent and body.owner_user_id != lead.owner_user_id:
        ensure_member(db, ctx, body.owner_user_id)
        record_activity(
            db,
            ctx,
            ActivityType.assigned,
            lead_id=lead.id,
            data={"to": str(body.owner_user_id) if body.owner_user_id else None},
        )
        lead.owner_user_id = body.owner_user_id

    if changed:
        # Record field names only; values may include personal data already in the lead.
        record_activity(
            db, ctx, ActivityType.updated, lead_id=lead.id, data={"fields": sorted(changed)}
        )
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("A lead with this email already exists", code="duplicate_lead") from exc
    return lead


def add_note(db: Session, ctx: OrgContext, lead_id: uuid.UUID, body: str) -> None:
    get_lead(db, ctx, lead_id)
    record_activity(db, ctx, ActivityType.note, lead_id=lead_id, body=body)


def soft_delete(db: Session, ctx: OrgContext, lead_ids: list[uuid.UUID]) -> int:
    ids = list(
        db.scalars(
            select(Lead.id).where(
                Lead.organization_id == ctx.org_id,
                Lead.id.in_(lead_ids),
                Lead.deleted_at.is_(None),
            )
        )
    )
    if ids:
        db.execute(update(Lead).where(Lead.id.in_(ids)).values(deleted_at=_now()))
        for lead_id in ids:
            record_activity(db, ctx, ActivityType.deleted, lead_id=lead_id)
        audit.record(
            db,
            "leads.deleted",
            org_id=ctx.org_id,
            actor_id=ctx.user_id,
            target_type="lead",
            data={"count": len(ids), "ids": [str(i) for i in ids[:50]]},
        )
    return len(ids)


def bulk_update(db: Session, ctx: OrgContext, body: BulkIn) -> int:
    """Apply one action to many leads. IDs outside the org are silently excluded."""
    if body.action == "delete":
        return soft_delete(db, ctx, body.ids)

    leads = list(
        db.scalars(
            select(Lead)
            .where(
                Lead.organization_id == ctx.org_id,
                Lead.id.in_(body.ids),
                Lead.deleted_at.is_(None),
            )
            .with_for_update()
        )
    )
    if body.action == "assign":
        try:
            owner = uuid.UUID(body.value) if body.value else None
        except ValueError as exc:
            raise AppError("value must be a user id", code="invalid_value") from exc
        ensure_member(db, ctx, owner)
        targets = [lead for lead in leads if lead.owner_user_id != owner]
        for lead in targets:
            lead.owner_user_id = owner
            record_activity(
                db,
                ctx,
                ActivityType.assigned,
                lead_id=lead.id,
                data={"to": str(owner) if owner else None, "bulk": True},
            )
    elif body.action == "set_status":
        try:
            status = LeadStatus(body.value or "")
        except ValueError as exc:
            raise AppError("value must be a lead status", code="invalid_value") from exc
        targets = [lead for lead in leads if lead.status != status]
        for lead in targets:
            record_activity(
                db,
                ctx,
                ActivityType.status_changed,
                lead_id=lead.id,
                data={"from": lead.status.value, "to": status.value, "bulk": True},
            )
            lead.status = status
    else:
        tag = (body.value or "").strip().lower()
        if not tag or len(tag) > 50:
            raise AppError("value must be a tag of 1-50 characters", code="invalid_value")
        if body.action == "add_tag":
            targets = [lead for lead in leads if tag not in lead.tags]
            for lead in targets:
                lead.tags = [*lead.tags, tag]
        else:
            targets = [lead for lead in leads if tag in lead.tags]
            for lead in targets:
                lead.tags = [t for t in lead.tags if t != tag]
    if len(targets) > 0:
        audit.record(
            db,
            f"leads.bulk_{body.action}",
            org_id=ctx.org_id,
            actor_id=ctx.user_id,
            target_type="lead",
            data={"count": len(targets), "value": body.value},
        )
    return len(targets)
