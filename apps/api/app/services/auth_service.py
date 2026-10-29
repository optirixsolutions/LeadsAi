"""Accounts, sessions, password reset, and email verification."""

import ipaddress
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, ConflictError
from app.core.security import (
    hash_password,
    new_token,
    password_needs_rehash,
    token_digest,
    verify_password,
)
from app.integrations.mailer import Email, Mailer
from app.models import AuthToken, TokenPurpose, User, UserSession
from app.services import audit


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "invalid_credentials"


class InvalidTokenError(AppError):
    status_code = 400
    code = "invalid_token"


def _now() -> datetime:
    return datetime.now(UTC)


def register(db: Session, mailer: Mailer, *, email: str, password: str, display_name: str) -> User:
    user = User(email=email, password_hash=hash_password(password), display_name=display_name)
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("An account with this email already exists") from exc
    audit.record(db, "auth.registered", actor_id=user.id, target_type="user", target_id=user.id)
    send_email_verification(db, mailer, user)
    return user


def authenticate(db: Session, *, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    # verify_password always runs a hash comparison so response time does not reveal accounts.
    ok = verify_password(password, user.password_hash if user else None)
    if not ok or user is None or user.disabled_at is not None:
        audit.record(db, "auth.login_failed", data={"email_domain": email.rpartition("@")[2]})
        db.commit()
        raise InvalidCredentialsError("Email or password is incorrect")
    if user.password_hash and password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


def _valid_ip(value: str | None) -> str | None:
    """The ASGI client host is not always an IP (proxies, sockets, test clients)."""
    try:
        return str(ipaddress.ip_address(value)) if value else None
    except ValueError:
        return None


def create_session(
    db: Session, user: User, *, ip: str | None, user_agent: str | None
) -> tuple[UserSession, str]:
    """Always issue a fresh token on login, so a pre-set cookie can never be adopted (fixation)."""
    token = new_token()
    now = _now()
    session = UserSession(
        user_id=user.id,
        token_hash=token_digest(token),
        expires_at=now + timedelta(hours=get_settings().session_ttl_hours),
        last_seen_at=now,
        ip_address=_valid_ip(ip),
        user_agent=(user_agent or "")[:400] or None,
    )
    db.add(session)
    db.flush()
    audit.record(db, "auth.login", actor_id=user.id, target_type="session", target_id=session.id)
    return session, token


def revoke_session(db: Session, session: UserSession, *, actor_id: uuid.UUID) -> None:
    if session.revoked_at is None:
        session.revoked_at = _now()
        audit.record(
            db,
            "auth.session_revoked",
            actor_id=actor_id,
            target_type="session",
            target_id=session.id,
        )


def revoke_session_token(db: Session, token: str) -> None:
    db.execute(
        update(UserSession)
        .where(UserSession.token_hash == token_digest(token), UserSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def revoke_all_sessions(
    db: Session, user_id: uuid.UUID, *, except_session: uuid.UUID | None = None
) -> None:
    stmt = update(UserSession).where(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
    )
    if except_session is not None:
        stmt = stmt.where(UserSession.id != except_session)
    db.execute(stmt.values(revoked_at=_now()))


def list_sessions(db: Session, user_id: uuid.UUID) -> list[UserSession]:
    return list(
        db.scalars(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > _now(),
            )
            .order_by(UserSession.last_seen_at.desc())
        )
    )


def change_password(
    db: Session, user: User, *, current: str, new: str, keep_session: uuid.UUID
) -> None:
    if not verify_password(current, user.password_hash):
        raise InvalidCredentialsError("Current password is incorrect")
    user.password_hash = hash_password(new)
    revoke_all_sessions(db, user.id, except_session=keep_session)
    audit.record(
        db, "auth.password_changed", actor_id=user.id, target_type="user", target_id=user.id
    )


# --- single-use tokens ------------------------------------------------------------------


def _issue_token(db: Session, user: User, purpose: TokenPurpose, ttl: timedelta) -> str:
    # Only the newest token of each purpose is valid.
    db.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user.id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
        )
        .values(used_at=_now())
    )
    token = new_token()
    db.add(
        AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=token_digest(token),
            expires_at=_now() + ttl,
        )
    )
    return token


def _consume_token(db: Session, token: str, purpose: TokenPurpose) -> User:
    row = db.execute(
        select(AuthToken, User)
        .join(User, User.id == AuthToken.user_id)
        .where(AuthToken.token_hash == token_digest(token), AuthToken.purpose == purpose)
        .with_for_update(of=AuthToken)
    ).first()
    if row is None:
        raise InvalidTokenError("This link is invalid or has expired")
    record, user = row
    if record.used_at is not None or record.expires_at <= _now() or user.disabled_at:
        raise InvalidTokenError("This link is invalid or has expired")
    record.used_at = _now()
    return user


def send_email_verification(db: Session, mailer: Mailer, user: User) -> None:
    s = get_settings()
    token = _issue_token(
        db, user, TokenPurpose.email_verification, timedelta(hours=s.email_verification_ttl_hours)
    )
    mailer.send(
        Email(
            to=user.email,
            subject="Verify your SalesIQ email",
            body=f"Confirm your email address: {s.web_base_url}/verify-email?token={token}",
        )
    )


def verify_email(db: Session, token: str) -> User:
    user = _consume_token(db, token, TokenPurpose.email_verification)
    if user.email_verified_at is None:
        user.email_verified_at = _now()
        audit.record(
            db, "auth.email_verified", actor_id=user.id, target_type="user", target_id=user.id
        )
    return user


def request_password_reset(db: Session, mailer: Mailer, email: str) -> None:
    """Silently does nothing for unknown or disabled accounts (no account enumeration)."""
    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.disabled_at is not None:
        return
    s = get_settings()
    token = _issue_token(
        db, user, TokenPurpose.password_reset, timedelta(minutes=s.password_reset_ttl_minutes)
    )
    audit.record(
        db, "auth.password_reset_requested", actor_id=user.id, target_type="user", target_id=user.id
    )
    mailer.send(
        Email(
            to=user.email,
            subject="Reset your SalesIQ password",
            body=(
                f"Reset your password: {s.web_base_url}/reset-password?token={token}\n"
                f"This link expires in {s.password_reset_ttl_minutes} minutes. "
                "If you did not request it, ignore this email."
            ),
        )
    )


def reset_password(db: Session, token: str, new_password: str) -> User:
    user = _consume_token(db, token, TokenPurpose.password_reset)
    user.password_hash = hash_password(new_password)
    # Receiving the email proves control of the address.
    if user.email_verified_at is None:
        user.email_verified_at = _now()
    revoke_all_sessions(db, user.id)
    audit.record(
        db, "auth.password_reset_completed", actor_id=user.id, target_type="user", target_id=user.id
    )
    return user
