"""CSV lead import (preview + idempotent commit) and export.

Small imports finish within the request, so the common case gets its result at once. Larger ones
go to a worker, because the largest allowed file took 36 s when measured. Either way an import
is one transaction, so a crash leaves nothing half-done and a retry starts clean.
"""

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import OrgContext
from app.core.errors import AppError, ConflictError
from app.core.rate_limit import RateLimitedError
from app.models import (
    ActivityType,
    Company,
    DuplicatePolicy,
    ImportStatus,
    Lead,
    LeadImport,
    LeadStatus,
)
from app.schemas.crm import ImportIn, LeadField
from app.services import audit
from app.services.lead_service import find_or_create_company, record_activity
from app.services.normalize import (
    company_domain_from_email,
    normalize_domain,
    normalize_email,
    parse_tags,
    split_full_name,
)

MAX_ROWS = 10_000
SYNC_ROW_LIMIT = 1_000
# Each waiting import can hold a 5 MB file, and it occupies a worker when its turn comes.
MAX_QUEUED_PER_ORG = 3
MAX_COLUMNS = 200
MAX_REPORTED_ERRORS = 100
PREVIEW_ROWS = 5

# Column length limits, mirroring the Lead model.
_LIMITS = {
    "first_name": 120,
    "last_name": 120,
    "title": 200,
    "phone": 40,
    "linkedin_url": 400,
    "source": 80,
    "company_name": 200,
}

# Header spellings recognized when suggesting a mapping.
_SYNONYMS: dict[LeadField, tuple[str, ...]] = {
    "email": ("email", "emailaddress", "workemail", "mail"),
    "first_name": ("firstname", "first", "givenname", "fname"),
    "last_name": ("lastname", "last", "surname", "familyname", "lname"),
    "full_name": ("name", "fullname", "contactname", "contact"),
    "title": ("title", "jobtitle", "position", "role"),
    "phone": ("phone", "phonenumber", "mobile", "telephone", "tel"),
    "linkedin_url": ("linkedin", "linkedinurl", "linkedinprofile"),
    "source": ("source", "leadsource"),
    "status": ("status", "leadstatus"),
    "tags": ("tags", "tag", "labels"),
    "company_name": ("company", "companyname", "organization", "account", "accountname"),
    "company_domain": ("domain", "companydomain"),
    "website": ("website", "url", "companywebsite", "web"),
}


class CsvError(AppError):
    status_code = 422
    code = "invalid_csv"


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def parse_csv(content: str) -> tuple[list[str], list[list[str]]]:
    """Parse CSV text into (headers, rows). Rejects files that exceed size limits."""
    text = content.lstrip("﻿")
    # Pick the delimiter that splits the header row most; csv.Sniffer guesses poorly on
    # small files. Ties (including none found) fall back to a comma.
    header_line = text.split("\n", 1)[0]
    delimiter = max(",;\t", key=lambda d: (header_line.count(d), d == ","))
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        headers = [h.strip() for h in next(reader)]
    except StopIteration as exc:
        raise CsvError("The file is empty") from exc
    except csv.Error as exc:
        raise CsvError(f"Could not read the header row: {exc}") from exc
    if not any(headers):
        raise CsvError("The header row is empty")
    if len(headers) > MAX_COLUMNS:
        raise CsvError(f"At most {MAX_COLUMNS} columns are supported")
    if len(set(headers)) != len(headers):
        raise CsvError("Column names must be unique")

    rows: list[list[str]] = []
    try:
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            rows.append(row)
            if len(rows) > MAX_ROWS:
                raise CsvError(f"At most {MAX_ROWS:,} rows per import")
    except csv.Error as exc:
        raise CsvError(f"Malformed CSV near row {len(rows) + 2}: {exc}") from exc
    return headers, rows


def suggest_mapping(headers: list[str]) -> dict[str, LeadField | None]:
    used: set[str] = set()
    out: dict[str, LeadField | None] = {}
    for header in headers:
        k = _key(header)
        match = next((f for f, names in _SYNONYMS.items() if k in names and f not in used), None)
        if match:
            used.add(match)
        out[header] = match
    return out


def idempotency_key(body: ImportIn) -> str:
    """Same file + same settings => same import. Different settings are a new import."""
    settings = json.dumps(
        {
            "mapping": dict(sorted(body.mapping.items())),
            "policy": body.duplicate_policy.value,
            "custom": body.unmapped_as_custom_fields,
            "source": body.source,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256()
    digest.update(body.content.lstrip("﻿").replace("\r\n", "\n").encode())
    digest.update(b"\0" + settings.encode())
    return digest.hexdigest()


@dataclass
class _Row:
    email: str | None = None
    values: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    custom: dict[str, str] = field(default_factory=dict)
    company_name: str | None = None
    company_domain: str | None = None


def _parse_row(headers: list[str], raw: list[str], body: ImportIn) -> _Row:
    """Turn one CSV row into normalized lead values. Raises ValueError with a reason."""
    cells = {h: (raw[i].strip() if i < len(raw) else "") for i, h in enumerate(headers)}
    row = _Row()
    full_name: str | None = None
    for header, target in body.mapping.items():
        if header not in cells:
            raise ValueError(f"Mapped column '{header}' is not in the file")
        value = cells[header]
        if not value:
            continue
        limit = _LIMITS.get(target)
        if limit and len(value) > limit:
            raise ValueError(f"{target} is longer than {limit} characters")
        if target == "email":
            row.email = normalize_email(value)
        elif target == "full_name":
            full_name = value
        elif target == "status":
            try:
                row.values["status"] = LeadStatus(value.lower())
            except ValueError as exc:
                allowed = ", ".join(s.value for s in LeadStatus)
                raise ValueError(f"status must be one of: {allowed}") from exc
        elif target == "tags":
            row.tags = [t[:50] for t in parse_tags(value)][:20]
        elif target == "linkedin_url":
            if not value.lower().startswith(("https://", "http://")):
                raise ValueError("linkedin_url must be an http(s) URL")
            row.values["linkedin_url"] = value
        elif target == "company_name":
            row.company_name = value
        elif target in ("company_domain", "website"):
            row.company_domain = normalize_domain(value) or row.company_domain
        else:
            row.values[target] = value

    if full_name and not (row.values.get("first_name") or row.values.get("last_name")):
        first, last = split_full_name(full_name)
        row.values["first_name"], row.values["last_name"] = first, last

    if body.unmapped_as_custom_fields:
        for header, value in cells.items():
            if header not in body.mapping and value:
                row.custom[header[:64]] = value[:1000]

    if not (row.email or row.values.get("first_name") or row.values.get("last_name")):
        raise ValueError("Row needs an email or a name")
    row.company_domain = row.company_domain or company_domain_from_email(row.email)
    return row


def preview(content: str) -> tuple[list[str], list[list[str]], int]:
    headers, rows = parse_csv(content)
    return headers, rows[:PREVIEW_ROWS], len(rows)


def run_import(db: Session, ctx: OrgContext, body: ImportIn) -> tuple[LeadImport, bool]:
    """Import leads. Returns (import, replayed). Replaying an identical import changes nothing."""
    key = idempotency_key(body)
    existing = db.scalar(
        select(LeadImport).where(
            LeadImport.organization_id == ctx.org_id, LeadImport.idempotency_key == key
        )
    )
    # A failed import did nothing, so submitting it again is a fresh attempt, not a replay.
    if existing and existing.status != ImportStatus.failed:
        return existing, True

    headers, rows = parse_csv(body.content)
    unknown = [h for h in body.mapping if h not in headers]
    if unknown:
        raise CsvError(f"Mapped columns not found in the file: {', '.join(unknown[:5])}")

    if len(rows) > SYNC_ROW_LIMIT:
        waiting = db.scalar(
            select(func.count())
            .select_from(LeadImport)
            .where(
                LeadImport.organization_id == ctx.org_id,
                LeadImport.status.in_((ImportStatus.queued, ImportStatus.running)),
            )
        )
        if (waiting or 0) >= MAX_QUEUED_PER_ORG:
            raise RateLimitedError("Too many large imports are waiting. Try again shortly.")
    record = existing or LeadImport(
        organization_id=ctx.org_id,
        idempotency_key=key,
        filename=body.filename,
        duplicate_policy=body.duplicate_policy,
        mapping=dict(body.mapping),
    )
    record.created_by_user_id = ctx.user_id
    record.total_rows = len(rows)
    record.status = ImportStatus.queued if len(rows) > SYNC_ROW_LIMIT else ImportStatus.running
    record.attempts = 0
    record.error_message = None
    if record.status == ImportStatus.queued:
        record.payload = body.model_dump(mode="json")
    db.add(record)
    try:
        db.flush()
    except IntegrityError as exc:
        # The same import is being committed by a concurrent request.
        raise ConflictError("This import is already being processed; refresh to see it") from exc
    if record.status == ImportStatus.queued:
        audit.record(
            db,
            "leads.import_queued",
            org_id=ctx.org_id,
            actor_id=ctx.user_id,
            target_type="lead_import",
            target_id=record.id,
            data={"filename": body.filename, "rows": len(rows)},
        )
        return record, False
    _apply(db, ctx, record, body, headers, rows)
    return record, False


def process_queued(db: Session, ctx: OrgContext, record: LeadImport) -> None:
    """Worker step, in one transaction. The stored file is removed in that same transaction."""
    body = ImportIn.model_validate(record.payload)
    headers, rows = parse_csv(body.content)
    _apply(db, ctx, record, body, headers, rows)


def _apply(
    db: Session,
    ctx: OrgContext,
    record: LeadImport,
    body: ImportIn,
    headers: list[str],
    rows: list[list[str]],
) -> None:
    record.created_count = record.updated_count = record.skipped_count = record.error_count = 0
    by_email = {
        lead.email: lead
        for lead in db.scalars(
            select(Lead).where(
                Lead.organization_id == ctx.org_id,
                Lead.deleted_at.is_(None),
                Lead.email.is_not(None),
            )
        )
    }
    seen_in_file: set[str] = set()
    companies: dict[tuple[str | None, str | None], Company | None] = {}
    errors: list[dict[str, Any]] = []

    for index, raw in enumerate(rows, start=2):  # row 1 is the header
        try:
            row = _parse_row(headers, raw, body)
        except ValueError as exc:
            record.error_count += 1
            if len(errors) < MAX_REPORTED_ERRORS:
                errors.append({"row": index, "error": str(exc)})
            continue

        if row.email and row.email in seen_in_file:
            record.skipped_count += 1
            continue
        if row.email:
            seen_in_file.add(row.email)

        ckey = (row.company_name, row.company_domain)
        if ckey not in companies:
            companies[ckey] = find_or_create_company(
                db, ctx, name=row.company_name, domain=row.company_domain
            )
        company = companies[ckey]

        match = by_email.get(row.email) if row.email else None
        if match is not None:
            if body.duplicate_policy == DuplicatePolicy.skip:
                record.skipped_count += 1
                continue
            # Update: fill in provided values; never blank out existing data.
            changed = [k for k, v in row.values.items() if getattr(match, k) != v]
            for k in changed:
                setattr(match, k, row.values[k])
            if company and match.company_id != company.id:
                match.company_id = company.id
                changed.append("company_id")
            if row.tags and set(row.tags) - set(match.tags):
                match.tags = [*match.tags, *[t for t in row.tags if t not in match.tags]][:20]
                changed.append("tags")
            if row.custom:
                match.custom_fields = {**match.custom_fields, **row.custom}
                changed.append("custom_fields")
            if changed:
                record.updated_count += 1
                record_activity(
                    db,
                    ctx,
                    ActivityType.updated,
                    lead_id=match.id,
                    data={"fields": sorted(set(changed)), "import_id": str(record.id)},
                )
            else:
                record.skipped_count += 1
            continue

        lead = Lead(
            organization_id=ctx.org_id,
            company_id=company.id if company else None,
            import_id=record.id,
            email=row.email,
            first_name=row.values.get("first_name"),
            last_name=row.values.get("last_name"),
            title=row.values.get("title"),
            phone=row.values.get("phone"),
            linkedin_url=row.values.get("linkedin_url"),
            source=row.values.get("source") or body.source or "csv_import",
            status=row.values.get("status", LeadStatus.new),
            tags=row.tags,
            custom_fields=row.custom,
        )
        db.add(lead)
        db.flush()
        if row.email:
            by_email[row.email] = lead
        record.created_count += 1
        record_activity(
            db, ctx, ActivityType.imported, lead_id=lead.id, data={"import_id": str(record.id)}
        )

    record.errors = errors
    audit.record(
        db,
        "leads.imported",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="lead_import",
        target_id=record.id,
        data={
            "filename": body.filename,
            "created": record.created_count,
            "updated": record.updated_count,
            "skipped": record.skipped_count,
            "errors": record.error_count,
        },
    )
    record.status = ImportStatus.completed
    record.payload = None
    record.lease_owner = None
    record.lease_expires_at = None


# --- export -----------------------------------------------------------------------------

EXPORT_COLUMNS = [
    "id",
    "first_name",
    "last_name",
    "email",
    "title",
    "phone",
    "linkedin_url",
    "company",
    "company_domain",
    "status",
    "source",
    "tags",
    "owner_user_id",
    "created_at",
]
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: object) -> str:
    """Neutralize spreadsheet formula injection by prefixing risky cells with a quote."""
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_PREFIXES) else text


def export_csv(rows: list[tuple[Lead, Company | None]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(EXPORT_COLUMNS)
    for lead, company in rows:
        writer.writerow(
            safe_cell(v)
            for v in (
                lead.id,
                lead.first_name,
                lead.last_name,
                lead.email,
                lead.title,
                lead.phone,
                lead.linkedin_url,
                company.name if company else None,
                company.domain if company else None,
                lead.status.value,
                lead.source,
                ";".join(lead.tags),
                lead.owner_user_id,
                lead.created_at.isoformat(),
            )
        )
    return out.getvalue()
