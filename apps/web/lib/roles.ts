/**
 * UI mirror of the API's role rules (apps/api/app/core/permissions.py), used only to
 * decide which controls to show. The API enforces every rule regardless.
 */
export const ROLES = ["owner", "admin", "manager", "sales_rep", "analyst"] as const;
export type Role = (typeof ROLES)[number];

export const ROLE_LABELS: Record<Role, string> = {
  owner: "Owner",
  admin: "Admin",
  manager: "Manager",
  sales_rep: "Sales rep",
  analyst: "Analyst (read-only)",
};

const ASSIGNABLE: Record<Role, readonly Role[]> = {
  owner: ROLES,
  admin: ["manager", "sales_rep", "analyst"],
  manager: [],
  sales_rep: [],
  analyst: [],
};

export function assignableRoles(actor: Role): readonly Role[] {
  return ASSIGNABLE[actor];
}

export function canManage(actor: Role, target: Role): boolean {
  return ASSIGNABLE[actor].includes(target);
}

export function hasPermission(permissions: readonly string[], permission: string): boolean {
  return permissions.includes(permission);
}
