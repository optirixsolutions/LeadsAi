import "server-only";

import { apiGet } from "./api";
import type { ApiResult } from "./api-result";
import type { Member, Stage } from "./crm";

/** GET an org-scoped API path, e.g. `orgGet(orgId, "/leads?limit=50")`. */
export function orgGet<T>(orgId: string, path: string): Promise<ApiResult<T>> {
  return apiGet<T>(`/api/v1/organizations/${orgId}${path}`);
}

export async function getMembers(orgId: string): Promise<Member[]> {
  const r = await orgGet<Member[]>(orgId, "/members");
  return r.ok ? r.data : [];
}

export async function getStages(orgId: string): Promise<ApiResult<Stage[]>> {
  return orgGet<Stage[]>(orgId, "/pipeline/stages");
}
