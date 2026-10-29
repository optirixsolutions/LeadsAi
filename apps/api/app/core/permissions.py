"""Role → permission matrix. The single source of truth for authorization decisions.

Checks happen server-side via `require(Permission.x)`; the frontend may read the matrix to
hide controls, but hiding is never the enforcement.
"""

import enum

from app.models.tenancy import Role


class Permission(enum.StrEnum):
    org_read = "org:read"
    org_update = "org:update"
    members_read = "members:read"
    members_invite = "members:invite"
    members_manage = "members:manage"  # change roles, remove members
    audit_read = "audit:read"


_ALL = frozenset(Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.owner: _ALL,
    Role.admin: _ALL,
    Role.manager: frozenset({Permission.org_read, Permission.members_read}),
    Role.sales_rep: frozenset({Permission.org_read, Permission.members_read}),
    Role.analyst: frozenset({Permission.org_read, Permission.members_read}),
}

# Roles each role may grant, change, or remove. Owners are managed only by owners, and
# admins cannot create peers, which prevents an admin from entrenching another admin.
ASSIGNABLE_ROLES: dict[Role, frozenset[Role]] = {
    Role.owner: frozenset(Role),
    Role.admin: frozenset({Role.manager, Role.sales_rep, Role.analyst}),
    Role.manager: frozenset(),
    Role.sales_rep: frozenset(),
    Role.analyst: frozenset(),
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]


def can_manage_role(actor: Role, target: Role) -> bool:
    return target in ASSIGNABLE_ROLES[actor]
