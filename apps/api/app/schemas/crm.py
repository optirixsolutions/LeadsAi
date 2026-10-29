"""Lead, company, import, pipeline, and analytics I/O schemas."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import ActivityType, DuplicatePolicy, ImportStatus, LeadStatus, StageKind
from app.schemas.auth import normalize_email

MAX_TAGS = 20
MAX_CUSTOM_FIELDS = 50
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_BULK_IDS = 500

Short = Annotated[str, Field(max_length=120)]
CustomValue = str | int | float | bool | None


def _strip_or_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


def _clean_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        t = t.strip().lower()
        if not t:
            continue
        if len(t) > 50:
            raise ValueError("Tags must be at most 50 characters")
        if t not in out:
            out.append(t)
    if len(out) > MAX_TAGS:
        raise ValueError(f"At most {MAX_TAGS} tags")
    return out


def _check_url(v: str | None) -> str | None:
    v = _strip_or_none(v)
    if v is not None and not v.lower().startswith(("https://", "http://")):
        # Rejects javascript:, data:, and other schemes that would be dangerous as links.
        raise ValueError("Must be an http(s) URL")
    return v


def _check_custom(v: dict[str, CustomValue]) -> dict[str, CustomValue]:
    if len(v) > MAX_CUSTOM_FIELDS:
        raise ValueError(f"At most {MAX_CUSTOM_FIELDS} custom fields")
    for key, value in v.items():
        if not 1 <= len(key) <= 64:
            raise ValueError("Custom field names must be 1-64 characters")
        if isinstance(value, str) and len(value) > 1000:
            raise ValueError("Custom field values must be at most 1000 characters")
    return v


# --- companies --------------------------------------------------------------------------


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=253)
    industry: str | None = Field(default=None, max_length=120)
    employee_count: int | None = Field(default=None, ge=0, le=10_000_000)
    country: str | None = Field(default=None, max_length=80)

    @field_validator("name", "industry", "country", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=253)
    industry: str | None = Field(default=None, max_length=120)
    employee_count: int | None = Field(default=None, ge=0, le=10_000_000)
    country: str | None = Field(default=None, max_length=80)


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    domain: str | None
    industry: str | None
    employee_count: int | None
    country: str | None
    created_at: datetime


class CompanyDetailOut(CompanyOut):
    lead_count: int


class CompanyPage(BaseModel):
    items: list[CompanyOut]
    next_cursor: str | None


class CompanySummary(BaseModel):
    id: uuid.UUID
    name: str
    domain: str | None


# --- leads ------------------------------------------------------------------------------


class _LeadFields(BaseModel):
    first_name: Short | None = None
    last_name: Short | None = None
    email: EmailStr | None = None
    title: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    linkedin_url: str | None = Field(default=None, max_length=400)
    source: str | None = Field(default=None, max_length=80)
    status: LeadStatus | None = None
    tags: list[str] | None = None
    custom_fields: dict[str, CustomValue] | None = None
    company_id: uuid.UUID | None = None
    # Convenience: find or create a company by name when no company_id is given.
    company_name: str | None = Field(default=None, max_length=200)
    owner_user_id: uuid.UUID | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return normalize_email(v) if v else None

    @field_validator("first_name", "last_name", "title", "phone", "source", "company_name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return _strip_or_none(v)

    @field_validator("linkedin_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return _check_url(v)

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _clean_tags(v)

    @field_validator("custom_fields")
    @classmethod
    def _custom(cls, v: dict[str, CustomValue] | None) -> dict[str, CustomValue] | None:
        return None if v is None else _check_custom(v)


class LeadCreate(_LeadFields):
    pass


class LeadUpdate(_LeadFields):
    """Partial update: only fields present in the request body change."""


class LeadOut(BaseModel):
    id: uuid.UUID
    first_name: str | None
    last_name: str | None
    email: str | None
    title: str | None
    phone: str | None
    linkedin_url: str | None
    source: str | None
    status: LeadStatus
    tags: list[str]
    custom_fields: dict[str, Any]
    company: CompanySummary | None
    owner_user_id: uuid.UUID | None
    import_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class LeadPage(BaseModel):
    items: list[LeadOut]
    next_cursor: str | None
    total: int


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: ActivityType
    body: str | None
    data: dict[str, Any]
    actor_user_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None
    created_at: datetime


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class BulkIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK_IDS)
    action: Literal["assign", "set_status", "add_tag", "remove_tag", "delete"]
    # assign: user id or null to unassign; set_status: a LeadStatus; add/remove_tag: tag
    value: str | None = Field(default=None, max_length=50)


class BulkOut(BaseModel):
    affected: int


# --- CSV import -------------------------------------------------------------------------

LeadField = Literal[
    "email",
    "first_name",
    "last_name",
    "full_name",
    "title",
    "phone",
    "linkedin_url",
    "source",
    "status",
    "tags",
    "company_name",
    "company_domain",
    "website",
]


class _CsvIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=MAX_CSV_BYTES)


class ImportPreviewIn(_CsvIn):
    pass


class ImportPreviewOut(BaseModel):
    headers: list[str]
    sample_rows: list[list[str]]
    total_rows: int
    suggested_mapping: dict[str, LeadField | None]


class ImportIn(_CsvIn):
    # CSV header -> lead field. Unlisted headers are ignored unless kept as custom fields.
    mapping: dict[str, LeadField] = Field(min_length=1, max_length=200)
    duplicate_policy: DuplicatePolicy = DuplicatePolicy.skip
    unmapped_as_custom_fields: bool = False
    source: str | None = Field(default=None, max_length=80)


class ImportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: ImportStatus
    duplicate_policy: DuplicatePolicy
    total_rows: int
    created_count: int
    updated_count: int
    skipped_count: int
    error_count: int
    errors: list[dict[str, Any]]
    created_at: datetime
    replayed: bool = False


# --- pipeline ---------------------------------------------------------------------------


class StageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    position: int
    kind: StageKind


class StageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: StageKind = StageKind.open


class StageUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


Money = Annotated[Decimal, Field(ge=0, le=Decimal("999999999999.99"), decimal_places=2)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class OpportunityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    stage_id: uuid.UUID
    lead_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    amount: Money | None = None
    currency: Currency = "USD"
    expected_close_date: date | None = None


class OpportunityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    stage_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    amount: Money | None = None
    currency: Currency | None = None
    expected_close_date: date | None = None


class OpportunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    stage_id: uuid.UUID
    lead_id: uuid.UUID | None
    company_id: uuid.UUID | None
    owner_user_id: uuid.UUID | None
    amount: Decimal | None
    currency: str
    expected_close_date: date | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StageSummary(BaseModel):
    stage_id: uuid.UUID
    name: str
    kind: StageKind
    count: int
    # Totals per currency; amounts in different currencies are never summed together.
    totals: dict[str, Decimal]


class PipelineSummaryOut(BaseModel):
    stages: list[StageSummary]


# --- analytics --------------------------------------------------------------------------


class OverviewOut(BaseModel):
    """Aggregates computed from stored records at request time. No estimates."""

    leads_total: int
    leads_added_30d: int
    leads_by_status: dict[str, int]
    open_opportunities: int
    open_pipeline_value: dict[str, Decimal]
    won_value_90d: dict[str, Decimal]
    won_count_90d: int
    recent_activity: list[ActivityOut]
