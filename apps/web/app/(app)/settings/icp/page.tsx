import type { Metadata } from "next";

import { Alert } from "@/components/ui/alert";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { IcpForm } from "@/features/intelligence/icp-form";
import { formatDateTime } from "@/lib/format";
import type { Icp } from "@/lib/intelligence";
import { orgGet } from "@/lib/org-api";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "ICP and scoring" };

export default async function IcpPage() {
  const { org } = await requireOrg();
  const orgId = org.organization_id;
  const versions = await orgGet<Icp[]>(orgId, "/icp/versions");
  if (!versions.ok) return <Alert tone="error">Could not load the ICP: {versions.message}</Alert>;
  const current = versions.data[0] ?? null;
  const canEdit = hasPermission(org.permissions, "icp:configure");

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="Ideal customer profile"
          description={
            current
              ? `Version ${current.version} is active. Saving creates a new version; earlier assessments keep the one they used.`
              : "No profile yet. Leads cannot be assessed until one is saved."
          }
        />
        <div className="px-5 py-4">
          {canEdit ? (
            <IcpForm key={current?.id ?? "new"} orgId={orgId} current={current} />
          ) : (
            <p className="text-sm text-fg-muted">Only owners and admins can change the profile.</p>
          )}
        </div>
      </Card>

      <Card>
        <CardHeader title="Version history" />
        {versions.data.length === 0 ? (
          <EmptyState title="No versions yet" body="Saved versions appear here." />
        ) : (
          <ul className="divide-y divide-border">
            {versions.data.map((v) => (
              <li key={v.id} className="flex flex-wrap justify-between gap-2 px-5 py-3 text-sm">
                <span className="font-medium">Version {v.version}</span>
                <time className="text-xs text-fg-subtle" dateTime={v.created_at}>
                  {formatDateTime(v.created_at)}
                </time>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
