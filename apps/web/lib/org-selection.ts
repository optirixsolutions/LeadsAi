export const CURRENT_ORG_COOKIE = "salesiq_org";

interface HasOrgId {
  organization_id: string;
}

/** Choose the active org: the preferred one if the user belongs to it, else the first. */
export function pickCurrentOrg<T extends HasOrgId>(memberships: T[], preferred?: string): T | null {
  return memberships.find((m) => m.organization_id === preferred) ?? memberships[0] ?? null;
}
