"""Outreach, approval, suppression, and settings schemas."""

import unicodedata
import uuid
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models import (
    ApprovalStatus,
    DeliveryStatus,
    DraftOrigin,
    DraftStatus,
    SuppressionKind,
    SuppressionReason,
)
from app.services.normalize import normalize_email

# A line break in a subject would start a new mail header.
Subject = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[^\r\n]*$"),
]
Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
OneLine = r"^[^\r\n]*$"


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: uuid.UUID
    subject: Subject
    body: Body


class DraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    subject: Subject | None = None
    body: Body | None = None


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    status: DraftStatus
    origin: DraftOrigin
    recipient: str
    subject: str
    body: str
    version: int
    content_hash: str
    flags: list[str]
    needs_edit: bool
    evidence_ids: list[str]
    rejection_note: str | None
    created_at: datetime
    updated_at: datetime


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    draft_id: uuid.UUID
    status: ApprovalStatus
    draft_version: int
    content_hash: str
    recipient: str
    requested_by_user_id: uuid.UUID | None
    decided_by_user_id: uuid.UUID | None
    note: str | None
    expires_at: datetime
    decided_at: datetime | None
    created_at: datetime


class ApprovalListItem(ApprovalOut):
    subject: str
    origin: DraftOrigin
    flags: list[str]


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The hash of the text on the approver's screen.
    content_hash: str = Field(min_length=64, max_length=64)


class ApprovalRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Note


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    draft_id: uuid.UUID
    status: DeliveryStatus
    adapter: str
    recipient: str
    message_id: str | None
    error_category: str | None
    provider_status: str | None
    resolved_by_user_id: uuid.UUID | None
    created_at: datetime
    finished_at: datetime | None


class DeliveryResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sent: bool


class Blocker(BaseModel):
    code: str
    message: str


class DraftSource(BaseModel):
    id: uuid.UUID
    source_type: str
    source_url: str | None
    # Text from outside, which may be trying to mislead whoever reads it.
    content: str


class DraftDetail(DraftOut):
    sources: list[DraftSource]
    approval: ApprovalOut | None
    deliveries: list[DeliveryOut]
    # What would stop this being sent right now.
    blockers: list[Blocker]


class SuppressionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: SuppressionKind = SuppressionKind.email
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=320)]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class SuppressionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: SuppressionKind
    value: str
    reason: SuppressionReason
    note: str | None
    created_at: datetime


class OutreachSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sends_enabled: bool
    sender_name: str | None
    sender_email: str | None
    postal_address: str | None
    timezone: str
    quiet_start_hour: int | None
    quiet_end_hour: int | None
    daily_limit: int
    recontact_days: int


class OutreachSettingsView(OutreachSettingsOut):
    # Why this server cannot send at all, which no setting here can change.
    server_blocker: Blocker | None


class OutreachSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sends_enabled: bool
    sender_name: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=120, pattern=OneLine)]
        | None
    ) = None
    sender_email: str | None = Field(default=None, max_length=320)
    postal_address: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=300, pattern=OneLine)]
        | None
    ) = None
    timezone: str = Field(default="UTC", max_length=64)
    quiet_start_hour: int | None = Field(default=None, ge=0, le=23)
    quiet_end_hour: int | None = Field(default=None, ge=0, le=23)
    daily_limit: int = Field(default=50, ge=1, le=10_000)
    recontact_days: int = Field(default=30, ge=0, le=365)

    @field_validator("sender_name", "postal_address")
    @classmethod
    def _one_line(cls, value: str | None) -> str | None:
        if value and any(unicodedata.category(c) in ("Cc", "Zl", "Zp", "Cf") for c in value):
            raise ValueError("This has to be one plain line")
        return value

    @field_validator("sender_email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return normalize_email(value)

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise ValueError("Unknown time zone") from exc
        return value

    @model_validator(mode="after")
    def _quiet_pair(self) -> "OutreachSettingsUpdate":
        if (self.quiet_start_hour is None) != (self.quiet_end_hour is None):
            raise ValueError("Quiet hours need both a start and an end")
        return self


class UnsubscribeResult(BaseModel):
    unsubscribed: bool
