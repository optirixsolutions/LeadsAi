import type { Metadata } from "next";

import { Alert } from "@/components/ui/alert";
import { SettingsForm } from "@/features/outreach/settings-form";
import { orgGet } from "@/lib/org-api";
import type { OutreachSettings } from "@/lib/outreach";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Outreach settings" };

export default async function OutreachSettingsPage() {
  const { org } = await requireOrg();
  const settings = await orgGet<OutreachSettings>(org.organization_id, "/outreach/settings");
  if (!settings.ok) return <Alert tone="error">Could not load settings: {settings.message}</Alert>;
  return (
    <SettingsForm
      orgId={org.organization_id}
      settings={settings.data}
      canEdit={hasPermission(org.permissions, "outreach:configure")}
    />
  );
}
