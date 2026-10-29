"""Organization, member, invitation, and audit endpoints.

Every org-scoped route resolves `OrgContext` through `require(...)`, which verifies the
caller's membership before any tenant data is touched.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.core.auth import (
    DbDep,
    OrgContext,
    PrincipalDep,
    require,
    require_json,
)
from app.core.permissions import Permission
from app.integrations.mailer import Mailer, get_mailer
from app.models import Organization, Role
from app.schemas.auth import TokenIn
from app.schemas.organizations import (
    AuditEntryOut,
    AuditPageOut,
    InvitationCreateIn,
    InvitationOut,
    InvitationPreviewOut,
    MemberOut,
    MemberUpdateIn,
    OrganizationCreateIn,
    OrganizationOut,
    OrganizationUpdateIn,
    OrganizationWithRoleOut,
)
from app.services import org_service

router = APIRouter(tags=["organizations"])

MailerDep = Annotated[Mailer, Depends(get_mailer)]
OrgRead = Annotated[OrgContext, Depends(require(Permission.org_read))]
OrgUpdate = Annotated[OrgContext, Depends(require(Permission.org_update))]
MembersRead = Annotated[OrgContext, Depends(require(Permission.members_read))]
MembersInvite = Annotated[OrgContext, Depends(require(Permission.members_invite))]
# Any member: used where finer role rules are applied by the service (e.g. leaving an org).
AnyMember = Annotated[OrgContext, Depends(require(Permission.members_read))]
AuditRead = Annotated[OrgContext, Depends(require(Permission.audit_read))]


def _with_role(org: Organization, role: Role) -> OrganizationWithRoleOut:
    return OrganizationWithRoleOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        created_at=org.created_at,
        role=role,
        permissions=org_service.permissions_for(role),
    )


@router.post("/organizations", status_code=201, response_model=OrganizationWithRoleOut)
def create_organization(
    body: OrganizationCreateIn, principal: PrincipalDep, db: DbDep
) -> OrganizationWithRoleOut:
    org = org_service.create_organization(db, principal, body.name)
    db.commit()
    return _with_role(org, Role.owner)


@router.get("/organizations", response_model=list[OrganizationWithRoleOut])
def list_organizations(principal: PrincipalDep, db: DbDep) -> list[OrganizationWithRoleOut]:
    return [_with_role(o, r) for o, r in org_service.list_my_organizations(db, principal.user.id)]


@router.get("/organizations/{org_id}", response_model=OrganizationWithRoleOut)
def get_organization(ctx: OrgRead, db: DbDep) -> OrganizationWithRoleOut:
    return _with_role(org_service.get_organization(db, ctx), ctx.role)


@router.patch("/organizations/{org_id}", response_model=OrganizationOut)
def update_organization(body: OrganizationUpdateIn, ctx: OrgUpdate, db: DbDep) -> Organization:
    org = org_service.update_organization(db, ctx, body.name)
    db.commit()
    return org


# --- members ----------------------------------------------------------------------------


@router.get("/organizations/{org_id}/members", response_model=list[MemberOut])
def list_members(ctx: MembersRead, db: DbDep) -> list[MemberOut]:
    return [
        MemberOut(
            id=m.id,
            user_id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=m.role,
            joined_at=m.created_at,
        )
        for m, u in org_service.list_members(db, ctx)
    ]


@router.patch("/organizations/{org_id}/members/{membership_id}", status_code=204)
def update_member(
    membership_id: uuid.UUID,
    body: MemberUpdateIn,
    ctx: Annotated[OrgContext, Depends(require(Permission.members_manage))],
    db: DbDep,
) -> Response:
    org_service.change_member_role(db, ctx, membership_id, body.role)
    db.commit()
    return Response(status_code=204)


@router.delete("/organizations/{org_id}/members/{membership_id}", status_code=204)
def remove_member(membership_id: uuid.UUID, ctx: AnyMember, db: DbDep) -> Response:
    # Any member may remove themselves; removing others is checked against role rules.
    org_service.remove_member(db, ctx, membership_id)
    db.commit()
    return Response(status_code=204)


# --- invitations ------------------------------------------------------------------------


@router.post("/organizations/{org_id}/invitations", status_code=201, response_model=InvitationOut)
def create_invitation(
    body: InvitationCreateIn, ctx: MembersInvite, db: DbDep, mailer: MailerDep
) -> InvitationOut:
    inv = org_service.create_invitation(db, mailer, ctx, email=body.email, role=body.role)
    db.commit()
    return InvitationOut.model_validate(inv)


@router.get("/organizations/{org_id}/invitations", response_model=list[InvitationOut])
def list_invitations(ctx: MembersInvite, db: DbDep) -> list[InvitationOut]:
    return [InvitationOut.model_validate(i) for i in org_service.list_pending_invitations(db, ctx)]


@router.delete("/organizations/{org_id}/invitations/{invitation_id}", status_code=204)
def revoke_invitation(invitation_id: uuid.UUID, ctx: MembersInvite, db: DbDep) -> Response:
    org_service.revoke_invitation(db, ctx, invitation_id)
    db.commit()
    return Response(status_code=204)


@router.post(
    "/invitations/preview",
    response_model=InvitationPreviewOut,
    dependencies=[Depends(require_json)],
)
def preview_invitation(body: TokenIn, db: DbDep) -> InvitationPreviewOut:
    inv, org = org_service.preview_invitation(db, body.token)
    return InvitationPreviewOut(
        organization_name=org.name, email=inv.email, role=inv.role, expires_at=inv.expires_at
    )


@router.post("/invitations/accept", response_model=OrganizationWithRoleOut)
def accept_invitation(body: TokenIn, principal: PrincipalDep, db: DbDep) -> OrganizationWithRoleOut:
    org, role = org_service.accept_invitation(db, principal, body.token)
    db.commit()
    return _with_role(org, role)


# --- audit ------------------------------------------------------------------------------


@router.get("/organizations/{org_id}/audit", response_model=AuditPageOut)
def list_audit(
    ctx: AuditRead,
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> AuditPageOut:
    items, next_cursor = org_service.list_audit(db, ctx, limit=limit, cursor=cursor)
    return AuditPageOut(
        items=[AuditEntryOut.model_validate(i) for i in items], next_cursor=next_cursor
    )
