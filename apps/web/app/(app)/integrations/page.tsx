import type { Metadata } from "next";

import { Alert } from "@/components/ui/alert";
import { Card, CardHeader } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { ConnectionPanel } from "@/features/integrations/connection-panel";
import { SERVER_BLOCKERS, type Integrations } from "@/lib/integrations";
import { orgGet } from "@/lib/org-api";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Integrations" };

export default async function IntegrationsPage() {
  const { org } = await requireOrg();
  const data = await orgGet<Integrations>(org.organization_id, "/integrations");
  return (
    <>
      <PageHeader title="Integrations" description="What this organization is connected to, and whether it is working." />
      {!data.ok ? (
        <Alert tone="error">Could not load integrations: {data.message}</Alert>
      ) : (
        <div className="space-y-6">
          {data.data.server_blocker && (
            <Alert tone="error">{SERVER_BLOCKERS[data.data.server_blocker] ?? "Sending is not available on this server."}</Alert>
          )}
          <ConnectionPanel
            orgId={org.organization_id}
            connections={data.data.connections}
            canManage={hasPermission(org.permissions, "integrations:manage")}
            included={data.data.integrations_included}
          />
          <Card>
            <CardHeader title="AI models" description="Whether each configured model can answer right now." />
            <ul className="divide-y divide-border">
              {data.data.models.map((m) => (
                <li key={m.model_key} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                  <code className="break-all text-xs">{m.model_key}</code>
                  <span className={m.available ? "text-accent" : "text-fg-subtle"}>
                    {m.available ? "Available" : "Not available"}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
          <p className="text-xs text-fg-subtle">
            Calendars, CRMs, enrichment, and payment providers are not built. They need a chosen provider and its credentials.
          </p>
        </div>
      )}
    </>
  );
}
