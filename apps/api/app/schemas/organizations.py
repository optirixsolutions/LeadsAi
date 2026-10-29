import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import Role
from app.schemas.auth import normalize_email

OrgName = Field(min_length=1, max_length=200)


class OrganizationCreateIn(BaseModel):
    name: str = OrgName

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name must not be blank")
        return v


class OrganizationUpdateIn(OrganizationCreateIn):
    pass


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class OrganizationWithRoleOut(OrganizationOut):
    role: Role
    permissions: list[str]


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    display_name: str
    role: Role
    joined_at: datetime


class MemberUpdateIn(BaseModel):
    role: Role


class InvitationCreateIn(BaseModel):
    email: EmailStr
    role: Role

    @field_validator("email")
    @classmethod
    def _norm(cls, v: str) -> str:
        return normalize_email(v)


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: Role
    created_at: datetime
    expires_at: datetime


class InvitationPreviewOut(BaseModel):
    organization_name: str
    email: str
    role: Role
    expires_at: datetime


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None
    target_type: str | None
    target_id: str | None
    request_id: str | None
    data: dict[str, Any]
    created_at: datetime


class AuditPageOut(BaseModel):
    items: list[AuditEntryOut]
    next_cursor: str | None
