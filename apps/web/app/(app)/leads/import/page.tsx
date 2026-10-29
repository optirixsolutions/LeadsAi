import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { PageHeader } from "@/components/ui/page-header";
import { ImportWizard } from "@/features/leads/import-wizard";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Import leads" };

export default async function ImportPage() {
  const { org } = await requireOrg();
  if (!hasPermission(org.permissions, "leads:import")) redirect("/leads");
  return (
    <>
      <p className="mb-2 text-sm">
        <Link href="/leads" className="text-fg-muted hover:text-fg">
          ← Leads
        </Link>
      </p>
      <PageHeader
        title="Import leads"
        description="Upload a CSV, check the column mapping, and choose how duplicates are handled. Re-uploading the same file with the same settings does nothing."
      />
      <ImportWizard orgId={org.organization_id} />
    </>
  );
}
