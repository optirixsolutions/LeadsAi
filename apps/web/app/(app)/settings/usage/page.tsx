import type { Metadata } from "next";

import { Alert } from "@/components/ui/alert";
import { UsagePanel } from "@/features/settings/usage-panel";
import type { Usage } from "@/lib/integrations";
import { orgGet } from "@/lib/org-api";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Plan and usage" };

export default async function UsagePage() {
  const { org } = await requireOrg();
  const usage = await orgGet<Usage>(org.organization_id, "/usage");
  if (!usage.ok) return <Alert tone="error">Could not load usage: {usage.message}</Alert>;
  return <UsagePanel orgId={org.organization_id} usage={usage.data} canChange={hasPermission(org.permissions, "billing:manage")} />;
}
