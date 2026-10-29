import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { apiGet, type MeOut } from "./api";
import { CURRENT_ORG_COOKIE, pickCurrentOrg } from "./org-selection";

export type Membership = MeOut["memberships"][number];

export interface AppContext {
  me: MeOut;
  org: Membership | null;
}

/**
 * Resolve the signed-in user and their selected organization, or redirect to sign-in.
 * The org cookie is only a preference: it is honored only if it names one of the
 * user's memberships, and the API re-checks membership on every request anyway.
 */
export async function requireAppContext(): Promise<AppContext> {
  const r = await apiGet<MeOut>("/api/v1/auth/me");
  if (!r.ok) {
    if (r.status === 401) redirect("/login");
    throw new Error(`Could not load your account: ${r.message}`);
  }
  const preferred = (await cookies()).get(CURRENT_ORG_COOKIE)?.value;
  return { me: r.data, org: pickCurrentOrg(r.data.memberships, preferred) };
}

export async function requireOrg(): Promise<AppContext & { org: Membership }> {
  const ctx = await requireAppContext();
  if (!ctx.org) redirect("/onboarding");
  return { ...ctx, org: ctx.org };
}

/** For public auth pages: the current user if signed in, otherwise null (never redirects). */
export async function optionalMe(): Promise<MeOut | null> {
  const r = await apiGet<MeOut>("/api/v1/auth/me");
  return r.ok ? r.data : null;
}
