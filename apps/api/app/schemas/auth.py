import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.models import Role

Password = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
Token = Field(min_length=20, max_length=200)


def normalize_email(v: str) -> str:
    return v.strip().lower()


class _EmailIn(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _norm(cls, v: str) -> str:
        return normalize_email(v)


class RegisterIn(_EmailIn):
    password: str = Password
    display_name: str = Field(default="", max_length=200)


class LoginIn(_EmailIn):
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class PasswordResetRequestIn(_EmailIn):
    pass


class PasswordResetConfirmIn(BaseModel):
    token: str = Token
    new_password: str = Password


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Password


class TokenIn(BaseModel):
    token: str = Token


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    email_verified: bool


class MembershipOut(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    role: Role
    permissions: list[str]


class MeOut(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    current: bool


class AcceptedOut(BaseModel):
    """Returned for requests whose outcome must not reveal whether an account exists."""

    status: str = "accepted"
