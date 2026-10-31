"""Authentication endpoints. Sessions are server-side and delivered as HttpOnly cookies."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from app.core.auth import (
    DbDep,
    PrincipalDep,
    clear_session_cookies,
    require_json,
    restore_context,
    session_cookie_name,
    set_session_cookies,
)
from app.core.config import get_settings
from app.core.errors import ForbiddenError, NotFoundError
from app.core.rate_limit import RateLimiter, get_rate_limiter
from app.integrations.mailer import Mailer, get_mailer
from app.models import User, UserSession
from app.schemas.auth import (
    AcceptedOut,
    LoginIn,
    MembershipOut,
    MeOut,
    PasswordChangeIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    RegisterIn,
    SessionOut,
    TokenIn,
    UserOut,
)
from app.services import auth_service, org_service

router = APIRouter(prefix="/auth", tags=["auth"])

MailerDep = Annotated[Mailer, Depends(get_mailer)]
LimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
JsonOnly = [Depends(require_json)]


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified_at is not None,
    )


@router.post("/register", status_code=201, response_model=UserOut, dependencies=JsonOnly)
def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    db: DbDep,
    mailer: MailerDep,
    limiter: LimiterDep,
) -> UserOut:
    if not get_settings().registration_enabled:
        raise ForbiddenError("Registration is disabled", code="registration_disabled")
    limiter.hit(f"register:ip:{_ip(request)}", get_settings().login_rate_limit_per_minute)
    user = auth_service.register(
        db, mailer, email=body.email, password=body.password, display_name=body.display_name
    )
    _, token = auth_service.create_session(
        db, user, ip=_ip(request), user_agent=request.headers.get("user-agent")
    )
    db.commit()
    set_session_cookies(response, token)
    return _user_out(user)


@router.post("/login", response_model=UserOut, dependencies=JsonOnly)
def login(
    body: LoginIn, request: Request, response: Response, db: DbDep, limiter: LimiterDep
) -> UserOut:
    limit = get_settings().login_rate_limit_per_minute
    limiter.hit(f"login:email:{body.email}", limit)
    limiter.hit(f"login:ip:{_ip(request)}", limit * 5)
    user = auth_service.authenticate(db, email=body.email, password=body.password)
    # Signing in again from the same browser replaces, rather than orphans, its old session.
    if previous := request.cookies.get(session_cookie_name()):
        auth_service.revoke_session_token(db, previous)
    _, token = auth_service.create_session(
        db, user, ip=_ip(request), user_agent=request.headers.get("user-agent")
    )
    db.commit()
    set_session_cookies(response, token)
    return _user_out(user)


@router.post("/logout", status_code=204)
def logout(principal: PrincipalDep, db: DbDep, response: Response) -> Response:
    auth_service.revoke_session(db, principal.session, actor_id=principal.user.id)
    db.commit()
    response.status_code = 204
    clear_session_cookies(response)
    return response


@router.get("/me", response_model=MeOut)
def me(principal: PrincipalDep, db: DbDep) -> MeOut:
    orgs = org_service.list_my_organizations(db, principal.user.id)
    return MeOut(
        user=_user_out(principal.user),
        memberships=[
            MembershipOut(
                organization_id=o.id,
                organization_name=o.name,
                organization_slug=o.slug,
                role=role,
                permissions=org_service.permissions_for(role),
            )
            for o, role in orgs
        ],
    )


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(principal: PrincipalDep, db: DbDep) -> list[SessionOut]:
    return [
        SessionOut(
            id=s.id,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            expires_at=s.expires_at,
            ip_address=str(s.ip_address) if s.ip_address else None,
            user_agent=s.user_agent,
            current=s.id == principal.session.id,
        )
        for s in auth_service.list_sessions(db, principal.user.id)
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(session_id: uuid.UUID, principal: PrincipalDep, db: DbDep) -> Response:
    target = db.scalar(
        select(UserSession).where(
            UserSession.id == session_id, UserSession.user_id == principal.user.id
        )
    )
    if target is None or target.revoked_at is not None:
        raise NotFoundError("Session not found")
    auth_service.revoke_session(db, target, actor_id=principal.user.id)
    db.commit()
    response = Response(status_code=204)
    if target.id == principal.session.id:
        clear_session_cookies(response)
    return response


@router.post("/password", status_code=204)
def change_password(
    body: PasswordChangeIn, principal: PrincipalDep, db: DbDep, limiter: LimiterDep
) -> Response:
    # Limits current-password guessing with a stolen session.
    limiter.hit(f"pwchange:user:{principal.user.id}", 5)
    auth_service.change_password(
        db,
        principal.user,
        current=body.current_password,
        new=body.new_password,
        keep_session=principal.session.id,
    )
    db.commit()
    return Response(status_code=204)


@router.post(
    "/password-reset/request", status_code=202, response_model=AcceptedOut, dependencies=JsonOnly
)
def request_password_reset(
    body: PasswordResetRequestIn,
    request: Request,
    db: DbDep,
    mailer: MailerDep,
    limiter: LimiterDep,
) -> AcceptedOut:
    limiter.hit(f"pwreset:email:{body.email}", 3)
    limiter.hit(f"pwreset:ip:{_ip(request)}", get_settings().login_rate_limit_per_minute)
    auth_service.request_password_reset(db, mailer, body.email)
    db.commit()
    return AcceptedOut()


@router.post("/password-reset/confirm", status_code=204, dependencies=JsonOnly)
def confirm_password_reset(
    body: PasswordResetConfirmIn, request: Request, db: DbDep, limiter: LimiterDep
) -> Response:
    limiter.hit(f"token:ip:{_ip(request)}", get_settings().login_rate_limit_per_minute)
    auth_service.reset_password(db, body.token, body.new_password)
    db.commit()
    response = Response(status_code=204)
    clear_session_cookies(response)
    return response


@router.post("/verify-email", response_model=UserOut, dependencies=JsonOnly)
def verify_email(body: TokenIn, request: Request, db: DbDep, limiter: LimiterDep) -> UserOut:
    limiter.hit(f"token:ip:{_ip(request)}", get_settings().login_rate_limit_per_minute)
    user = auth_service.verify_email(db, body.token)
    db.commit()
    return _user_out(user)


@router.post("/verify-email/resend", status_code=202, response_model=AcceptedOut)
def resend_verification(
    principal: PrincipalDep, db: DbDep, mailer: MailerDep, limiter: LimiterDep
) -> AcceptedOut:
    limiter.hit(f"verify:user:{principal.user.id}", 3)
    if principal.user.email_verified_at is None:
        auth_service.send_email_verification(db, mailer, principal.user)
        db.commit()
        restore_context(db, principal)
    return AcceptedOut()
