import type { components } from "@salesiq/contracts";
import type { Metadata } from "next";

import { Alert } from "@/components/ui/alert";
import { Card, CardHeader } from "@/components/ui/card";
import { AuditLog } from "@/features/settings/audit-log";
import { OrgNameForm } from "@/features/settings/org-name-form";
import { apiGet } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { hasPermission, ROLE_LABELS, type Role } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Organization" };

type Org = components["schemas"]["OrganizationWithRoleOut"];
type AuditPage = components["schemas"]["AuditPageOut"];

export default async function OrganizationPage() {
  const { org: membership } = await requireOrg();
  const base = `/api/v1/organizations/${membership.organization_id}`;
  const canAudit = hasPermission(membership.permissions, "audit:read");
  const [org, audit] = await Promise.all([
    apiGet<Org>(base),
    canAudit ? apiGet<AuditPage>(`${base}/audit?limit=25`) : Promise.resolve(null),
  ]);
  if (!org.ok) return <Alert tone="error">Could not load organization: {org.message}</Alert>;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Details" />
        <div className="space-y-5 px-5 py-4">
          {hasPermission(membership.permissions, "org:update") ? (
            <OrgNameForm orgId={org.data.id} name={org.data.name} />
          ) : (
            <p className="text-sm">{org.data.name}</p>
          )}
          <dl className="grid gap-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs text-fg-subtle">Identifier</dt>
              <dd className="mt-0.5 font-mono text-xs">{org.data.slug}</dd>
            </div>
            <div>
              <dt className="text-xs text-fg-subtle">Created</dt>
              <dd className="mt-0.5">{formatDate(org.data.created_at)}</dd>
            </div>
            <div>
              <dt className="text-xs text-fg-subtle">Your role</dt>
              <dd className="mt-0.5">{ROLE_LABELS[org.data.role as Role]}</dd>
            </div>
          </dl>
        </div>
      </Card>

      {audit &&
        (audit.ok ? (
          <AuditLog orgId={org.data.id} initial={audit.data} />
        ) : (
          <Alert tone="error">Could not load audit log: {audit.message}</Alert>
        ))}
    </div>
  );
}
