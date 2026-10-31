"""Request authentication and organization authorization dependencies.

Flow per request:
  session cookie → active session row → enabled user        (get_principal)
  → CSRF check for unsafe methods
  → membership in the org named by the path, looked up under user-only RLS context
  → tenant context set to that org for the rest of the transaction
  → permission check                                         (require)

The organization is never taken on trust from the client: a path org_id only selects
which of the caller's memberships applies. Non-members get 404 so org IDs cannot be probed.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db, set_tenant_context
from app.core.errors import AccessLostError, AppError, ForbiddenError, NotFoundError
from app.core.permissions import Permission, has_permission
from app.core.security import csrf_matches, csrf_token_for, token_digest
from app.models import Membership, Role, User, UserSession

SESSION_COOKIE = "salesiq_session"
CSRF_COOKIE = "salesiq_csrf"
# A browser only accepts this prefix from HTTPS, for the whole host, with no Domain, so a
# compromised sibling subdomain cannot plant a cookie. It needs HTTPS, so it is not used locally.
_HOST_PREFIX = "__Host-"


def session_cookie_name() -> str:
    return (_HOST_PREFIX if get_settings().cookie_secure else "") + SESSION_COOKIE


def csrf_cookie_name() -> str:
    return (_HOST_PREFIX if get_settings().cookie_secure else "") + CSRF_COOKIE


CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_LAST_SEEN_RESOLUTION = timedelta(minutes=5)


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class CsrfError(AppError):
    status_code = 403
    code = "csrf_failed"


class UnsupportedMediaError(AppError):
    status_code = 415
    code = "unsupported_media_type"


@dataclass(frozen=True)
class Principal:
    user: User
    session: UserSession
    token: str


@dataclass(frozen=True)
class OrgContext:
    principal: Principal
    org_id: uuid.UUID
    role: Role
    membership_id: uuid.UUID

    @property
    def user_id(self) -> uuid.UUID:
        return self.principal.user.id


DbDep = Annotated[Session, Depends(get_db)]


def require_json(request: Request) -> None:
    """Reject non-JSON bodies on unsafe methods.

    Browsers cannot send cross-origin `application/json` without a CORS preflight, so this
    blocks form-based CSRF against endpoints that run before a session exists (login, register).
    """
    if request.method in SAFE_METHODS:
        return
    has_body = request.headers.get("content-length", "0") != "0" or (
        "transfer-encoding" in request.headers
    )
    if not has_body:
        return
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype != "application/json":
        raise UnsupportedMediaError("Content-Type must be application/json")


def _now() -> datetime:
    return datetime.now(UTC)


def get_principal(request: Request, db: DbDep) -> Principal:
    token = request.cookies.get(session_cookie_name())
    if not token:
        raise UnauthorizedError("Authentication required")

    now = _now()
    row = db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.token_hash == token_digest(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
    ).first()
    if row is None:
        raise UnauthorizedError("Session expired or invalid")
    session, user = row
    if user.disabled_at is not None:
        raise UnauthorizedError("Account disabled")

    idle = timedelta(hours=get_settings().session_idle_timeout_hours)
    if session.last_seen_at < now - idle:
        session.revoked_at = now
        db.commit()
        raise UnauthorizedError("Session expired due to inactivity")

    if request.method not in SAFE_METHODS:
        require_json(request)
        if not csrf_matches(token, request.headers.get(CSRF_HEADER)):
            raise CsrfError("Missing or invalid CSRF token")

    if session.last_seen_at < now - _LAST_SEEN_RESOLUTION:
        session.last_seen_at = now
        db.commit()

    set_tenant_context(db, user_id=user.id)
    return Principal(user=user, session=session, token=token)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def get_org_context(org_id: uuid.UUID, principal: PrincipalDep, db: DbDep) -> OrgContext:
    membership = db.scalar(
        select(Membership).where(
            Membership.organization_id == org_id, Membership.user_id == principal.user.id
        )
    )
    if membership is None:
        raise NotFoundError("Organization not found")
    set_tenant_context(db, user_id=principal.user.id, org_id=org_id)
    return OrgContext(
        principal=principal, org_id=org_id, role=membership.role, membership_id=membership.id
    )


def worker_context(db: Session, org_id: uuid.UUID, user_id: uuid.UUID | None) -> OrgContext:
    """The requester's authority for queued work, looked up again now: they may have left,
    changed role, or been disabled since they asked. Also sets the tenant for this transaction."""
    set_tenant_context(db, user_id=user_id, org_id=org_id)
    user = db.get(User, user_id) if user_id else None
    membership = db.scalar(
        select(Membership).where(
            Membership.organization_id == org_id, Membership.user_id == user_id
        )
    )
    if user is None or user.disabled_at is not None or membership is None:
        raise AccessLostError("The person who started this no longer has access")
    # A worker acts for a person but has no browser session; nothing downstream reads those.
    principal = Principal(user=user, session=cast(UserSession, None), token="")
    return OrgContext(
        principal=principal, org_id=org_id, role=membership.role, membership_id=membership.id
    )


def require(permission: Permission) -> Callable[..., OrgContext]:
    def dependency(
        ctx: Annotated[OrgContext, Depends(get_org_context)],
    ) -> OrgContext:
        if not has_permission(ctx.role, permission):
            raise ForbiddenError(f"Your role does not allow {permission.value}")
        return ctx

    return dependency


def restore_context(db: Session, ctx: OrgContext | Principal) -> None:
    """Re-apply tenant context after a commit inside a request."""
    if isinstance(ctx, OrgContext):
        set_tenant_context(db, user_id=ctx.user_id, org_id=ctx.org_id)
    else:
        set_tenant_context(db, user_id=ctx.user.id)


def set_session_cookies(response: Response, token: str) -> None:
    s = get_settings()
    max_age = s.session_ttl_hours * 3600
    common = {"max_age": max_age, "secure": s.cookie_secure, "samesite": "lax", "path": "/"}
    response.set_cookie(session_cookie_name(), token, httponly=True, **common)  # type: ignore[arg-type]
    # Readable by the web app so it can echo it in the CSRF header.
    response.set_cookie(csrf_cookie_name(), csrf_token_for(token), httponly=False, **common)  # type: ignore[arg-type]


def clear_session_cookies(response: Response) -> None:
    s = get_settings()
    for name in (session_cookie_name(), csrf_cookie_name()):
        response.delete_cookie(name, path="/", secure=s.cookie_secure, samesite="lax")
