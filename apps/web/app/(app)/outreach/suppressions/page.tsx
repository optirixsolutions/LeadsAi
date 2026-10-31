import type { Metadata } from "next";

import { Alert } from "@/components/ui/alert";
import { SuppressionManager } from "@/features/outreach/suppression-manager";
import { orgGet } from "@/lib/org-api";
import type { Suppression } from "@/lib/outreach";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Suppression list" };

export default async function SuppressionsPage() {
  const { org } = await requireOrg();
  const entries = await orgGet<Suppression[]>(org.organization_id, "/outreach/suppressions");
  if (!entries.ok) return <Alert tone="error">Could not load the list: {entries.message}</Alert>;
  return (
    <SuppressionManager
      orgId={org.organization_id}
      entries={entries.data}
      canAdd={hasPermission(org.permissions, "outreach:write")}
      canRemove={hasPermission(org.permissions, "outreach:approve")}
    />
  );
}
