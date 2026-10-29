import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { LeadForm } from "@/features/leads/lead-form";
import { getMembers } from "@/lib/org-api";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "New lead" };

export default async function NewLeadPage() {
  const { org } = await requireOrg();
  if (!hasPermission(org.permissions, "leads:write")) redirect("/leads");
  const members = await getMembers(org.organization_id);
  return (
    <>
      <p className="mb-2 text-sm">
        <Link href="/leads" className="text-fg-muted hover:text-fg">
          ← Leads
        </Link>
      </p>
      <PageHeader title="New lead" description="Duplicates are detected by email within your organization." />
      <Card className="max-w-3xl p-5">
        <LeadForm orgId={org.organization_id} members={members} />
      </Card>
    </>
  );
}
