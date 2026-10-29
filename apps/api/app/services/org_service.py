"""Organizations, memberships, and invitations.

Callers must have set tenant context (see app.core.auth). Authorization rules beyond the
permission matrix (who may manage which role, last-owner protection) live here.
"""

import base64
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.core.auth import OrgContext, Principal
from app.core.config import get_settings
from app.core.db import set_tenant_context
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.permissions import ROLE_PERMISSIONS, can_manage_role
from app.core.security import new_token, token_digest
from app.integrations.mailer import Email, Mailer
from app.models import AuditLog, Invitation, Membership, Organization, Role, User
from app.services import audit
from app.services.auth_service import InvalidTokenError
from app.services.pipeline_service import seed_default_stages


def _now() -> datetime:
    return datetime.now(UTC)


def permissions_for(role: Role) -> list[str]:
    return sorted(p.value for p in ROLE_PERMISSIONS[role])


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"
    return f"{base}-{secrets.token_hex(3)}"


# --- organizations ----------------------------------------------------------------------


def create_organization(db: Session, principal: Principal, name: str) -> Organization:
    org = Organization(id=uuid.uuid4(), name=name, slug=_slugify(name))
    # RLS requires the new org to be the current tenant before its rows can be written.
    set_tenant_context(db, user_id=principal.user.id, org_id=org.id)
    db.add(org)
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=principal.user.id, role=Role.owner))
    seed_default_stages(db, org.id)
    audit.record(
        db,
        "org.created",
        org_id=org.id,
        actor_id=principal.user.id,
        target_type="organization",
        target_id=org.id,
        data={"name": name},
    )
    return org


def list_my_organizations(db: Session, user_id: uuid.UUID) -> list[tuple[Organization, Role]]:
    rows = db.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user_id)
        .order_by(Organization.name)
    ).all()
    return [(o, r) for o, r in rows]


def get_organization(db: Session, ctx: OrgContext) -> Organization:
    org = db.get(Organization, ctx.org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return org


def update_organization(db: Session, ctx: OrgContext, name: str) -> Organization:
    org = get_organization(db, ctx)
    old = org.name
    org.name = name
    audit.record(
        db,
        "org.updated",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="organization",
        target_id=org.id,
        data={"name": [old, name]},
    )
    return org


# --- members ----------------------------------------------------------------------------


def list_members(db: Session, ctx: OrgContext) -> list[tuple[Membership, User]]:
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == ctx.org_id)
        .order_by(Membership.created_at)
    ).all()
    return [(m, u) for m, u in rows]


def _lock_org(db: Session, org_id: uuid.UUID) -> None:
    """Serialize membership changes per org so concurrent removals or demotions cannot
    both pass the last-owner check."""
    db.execute(select(Organization.id).where(Organization.id == org_id).with_for_update())


def _get_membership(db: Session, ctx: OrgContext, membership_id: uuid.UUID) -> Membership:
    # The explicit org filter is the primary check; RLS is the backstop.
    m = db.scalar(
        select(Membership).where(
            Membership.id == membership_id, Membership.organization_id == ctx.org_id
        )
    )
    if m is None:
        raise NotFoundError("Member not found")
    return m


def _owner_count(db: Session, org_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.organization_id == org_id, Membership.role == Role.owner)
        )
        or 0
    )


def change_member_role(
    db: Session, ctx: OrgContext, membership_id: uuid.UUID, new_role: Role
) -> Membership:
    _lock_org(db, ctx.org_id)
    m = _get_membership(db, ctx, membership_id)
    if m.id == ctx.membership_id:
        raise ForbiddenError("You cannot change your own role")
    if not (can_manage_role(ctx.role, m.role) and can_manage_role(ctx.role, new_role)):
        raise ForbiddenError("Your role cannot assign or modify this role")
    if m.role == new_role:
        return m
    if m.role == Role.owner and _owner_count(db, ctx.org_id) <= 1:
        raise ConflictError("An organization must keep at least one owner")
    old = m.role
    m.role = new_role
    audit.record(
        db,
        "member.role_changed",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="membership",
        target_id=m.id,
        data={"user_id": str(m.user_id), "from": old.value, "to": new_role.value},
    )
    return m


def remove_member(db: Session, ctx: OrgContext, membership_id: uuid.UUID) -> None:
    _lock_org(db, ctx.org_id)
    m = _get_membership(db, ctx, membership_id)
    leaving_self = m.id == ctx.membership_id
    if not leaving_self and not can_manage_role(ctx.role, m.role):
        raise ForbiddenError("Your role cannot remove this member")
    if m.role == Role.owner and _owner_count(db, ctx.org_id) <= 1:
        raise ConflictError("An organization must keep at least one owner")
    db.delete(m)
    audit.record(
        db,
        "member.left" if leaving_self else "member.removed",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="membership",
        target_id=m.id,
        data={"user_id": str(m.user_id), "role": m.role.value},
    )


# --- invitations ------------------------------------------------------------------------


def create_invitation(
    db: Session, mailer: Mailer, ctx: OrgContext, *, email: str, role: Role
) -> Invitation:
    if not can_manage_role(ctx.role, role):
        raise ForbiddenError("Your role cannot invite members with this role")
    already = db.scalar(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == ctx.org_id, User.email == email)
    )
    if already:
        raise ConflictError("This person is already a member")

    now = _now()
    # Re-inviting replaces any pending invitation for the same address, but only one the
    # actor could have revoked directly (an admin must not displace an owner's invite).
    pending = list(
        db.scalars(
            select(Invitation)
            .where(
                Invitation.organization_id == ctx.org_id,
                Invitation.email == email,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
            .with_for_update()
        )
    )
    if any(not can_manage_role(ctx.role, p.role) for p in pending):
        raise ConflictError("A pending invitation you cannot replace already exists")
    for p in pending:
        p.revoked_at = now

    token = new_token()
    inv = Invitation(
        organization_id=ctx.org_id,
        email=email,
        role=role,
        token_hash=token_digest(token),
        invited_by_user_id=ctx.user_id,
        expires_at=now + timedelta(hours=get_settings().invitation_ttl_hours),
    )
    db.add(inv)
    db.flush()
    org = get_organization(db, ctx)
    audit.record(
        db,
        "invitation.created",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="invitation",
        target_id=inv.id,
        data={"email": email, "role": role.value},
    )
    mailer.send(
        Email(
            to=email,
            subject=f"You're invited to {org.name} on SalesIQ",
            body=(
                f"{ctx.principal.user.display_name or ctx.principal.user.email} invited you to "
                f"join {org.name} as {role.value}.\n"
                f"Accept: {get_settings().web_base_url}/invite?token={token}"
            ),
        )
    )
    return inv


def list_pending_invitations(db: Session, ctx: OrgContext) -> list[Invitation]:
    return list(
        db.scalars(
            select(Invitation)
            .where(
                Invitation.organization_id == ctx.org_id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > _now(),
            )
            .order_by(Invitation.created_at.desc())
        )
    )


def revoke_invitation(db: Session, ctx: OrgContext, invitation_id: uuid.UUID) -> None:
    inv = db.scalar(
        select(Invitation)
        .where(Invitation.id == invitation_id, Invitation.organization_id == ctx.org_id)
        .with_for_update()
    )
    if inv is None or inv.revoked_at is not None or inv.accepted_at is not None:
        raise NotFoundError("Invitation not found")
    if not can_manage_role(ctx.role, inv.role):
        raise ForbiddenError("Your role cannot revoke this invitation")
    inv.revoked_at = _now()
    audit.record(
        db,
        "invitation.revoked",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="invitation",
        target_id=inv.id,
    )


def _load_invitation_by_token(
    db: Session, token: str, user_id: uuid.UUID | None, *, lock: bool = False
) -> tuple[Invitation, Organization]:
    """Resolve a raw token to its invitation, entering that org's tenant context.

    `lock` takes a row lock so a concurrent revoke or second accept waits, then sees the
    invitation as already used.
    """
    found = db.execute(
        select(func.invitation_lookup(token_digest(token)).table_valued("id", "organization_id"))
    ).first()
    if found is None:
        raise InvalidTokenError("This invitation is invalid or has expired")
    inv_id, org_id = found
    set_tenant_context(db, user_id=user_id, org_id=org_id)
    inv = db.get(Invitation, inv_id, with_for_update=lock)
    org = db.get(Organization, org_id)
    if (
        inv is None
        or org is None
        or inv.accepted_at is not None
        or inv.revoked_at is not None
        or inv.expires_at <= _now()
    ):
        raise InvalidTokenError("This invitation is invalid or has expired")
    return inv, org


def preview_invitation(db: Session, token: str) -> tuple[Invitation, Organization]:
    return _load_invitation_by_token(db, token, user_id=None)


def accept_invitation(db: Session, principal: Principal, token: str) -> tuple[Organization, Role]:
    inv, org = _load_invitation_by_token(db, token, user_id=principal.user.id, lock=True)
    if inv.email != principal.user.email:
        # The token alone is not enough: it must be redeemed by the invited address.
        raise ForbiddenError("This invitation was sent to a different email address")
    if principal.user.email_verified_at is None:
        # Otherwise anyone holding a leaked link could register the address and join.
        raise ForbiddenError(
            "Verify your email address before accepting this invitation",
            code="email_unverified",
        )
    existing = db.scalar(
        select(Membership).where(
            Membership.organization_id == org.id, Membership.user_id == principal.user.id
        )
    )
    if existing is None:
        db.add(Membership(organization_id=org.id, user_id=principal.user.id, role=inv.role))
        role = inv.role
    else:
        # Never downgrade or upgrade an existing member through an invitation.
        role = existing.role
    inv.accepted_at = _now()
    audit.record(
        db,
        "invitation.accepted",
        org_id=org.id,
        actor_id=principal.user.id,
        target_type="invitation",
        target_id=inv.id,
        data={"role": inv.role.value},
    )
    return org, role


# --- audit ------------------------------------------------------------------------------


class InvalidCursorError(AppError):
    code = "invalid_cursor"


def _encode_cursor(entry: AuditLog) -> str:
    raw = f"{entry.created_at.isoformat()}|{entry.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        ts, _, ident = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        return datetime.fromisoformat(ts), uuid.UUID(ident)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursorError("Invalid pagination cursor") from exc


def list_audit(
    db: Session, ctx: OrgContext, *, limit: int, cursor: str | None
) -> tuple[list[AuditLog], str | None]:
    q = select(AuditLog).where(AuditLog.organization_id == ctx.org_id)
    if cursor:
        ts, ident = _decode_cursor(cursor)
        q = q.where(tuple_(AuditLog.created_at, AuditLog.id) < tuple_(ts, ident))
    rows = list(
        db.scalars(q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1))
    )
    next_cursor = _encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return rows[:limit], next_cursor
