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
    leads_read = "leads:read"
    leads_write = "leads:write"  # create, edit, assign, notes, companies
    leads_delete = "leads:delete"  # soft delete, including bulk
    leads_import = "leads:import"
    leads_export = "leads:export"
    pipeline_read = "pipeline:read"
    pipeline_write = "pipeline:write"  # create and move opportunities
    pipeline_configure = "pipeline:configure"  # stages
    intelligence_read = "intelligence:read"  # ICP, evidence, assessments, briefs
    research_write = "research:write"  # add or fetch evidence, request briefs
    assessments_run = "assessments:run"
    # Release quarantined evidence and approve assessments. Withheld from reps, who could
    # otherwise add a planted instruction and then wave it through themselves.
    intelligence_review = "intelligence:review"
    icp_configure = "icp:configure"
    workflows_read = "workflows:read"
    workflows_run = "workflows:run"  # start, cancel, and resume
    outreach_read = "outreach:read"
    outreach_write = "outreach:write"  # draft, edit, ask for approval, add to suppression
    outreach_send = "outreach:send"  # send what someone with outreach:approve has approved
    # Withheld from reps, who could otherwise write an email and wave it through themselves.
    outreach_approve = "outreach:approve"  # decide approvals, remove suppressions
    outreach_configure = "outreach:configure"  # sender identity, limits, turning sending on


_ALL = frozenset(Permission)
_READ = frozenset(
    {
        Permission.org_read,
        Permission.members_read,
        Permission.leads_read,
        Permission.pipeline_read,
        Permission.intelligence_read,
        Permission.workflows_read,
        Permission.outreach_read,
    }
)
_SELL = _READ | {
    Permission.leads_write,
    Permission.pipeline_write,
    Permission.research_write,
    Permission.assessments_run,
    Permission.workflows_run,
    Permission.outreach_write,
    Permission.outreach_send,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.owner: _ALL,
    Role.admin: _ALL,
    # Managers run the team's data: bulk changes, imports, and exports.
    Role.manager: _SELL
    | {
        Permission.leads_delete,
        Permission.leads_import,
        Permission.leads_export,
        Permission.intelligence_review,
        Permission.outreach_approve,
    },
    Role.sales_rep: _SELL,
    # Read-only. Export is withheld: it is the easiest path to bulk data exfiltration.
    Role.analyst: _READ,
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
