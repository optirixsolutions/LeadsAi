import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { PageHeader } from "@/components/ui/page-header";
import { LeadFilters } from "@/features/leads/lead-filters";
import { LeadsTable } from "@/features/leads/leads-table";
import { formatNumber, type LeadPage } from "@/lib/crm";
import { getMembers, orgGet } from "@/lib/org-api";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Leads" };

type Search = { q?: string; status?: string; fit?: string; owner?: string; sort?: string; cursor?: string; import_id?: string };

const PASSTHROUGH = ["q", "status", "fit", "owner", "sort", "import_id"] as const;

export default async function LeadsPage({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const { org } = await requireOrg();
  const query = new URLSearchParams({ limit: "50" });
  for (const key of PASSTHROUGH) if (sp[key]) query.set(key, sp[key]!);
  if (sp.cursor) query.set("cursor", sp.cursor);

  const [page, members] = await Promise.all([
    orgGet<LeadPage>(org.organization_id, `/leads?${query}`),
    getMembers(org.organization_id),
  ]);
  const can = (p: string) => hasPermission(org.permissions, p);

  const filterQuery = new URLSearchParams();
  for (const key of PASSTHROUGH) if (sp[key]) filterQuery.set(key, sp[key]!);
  const exportHref = `/api/v1/organizations/${org.organization_id}/leads/export?${filterQuery}`;
  const nextHref = page.ok && page.data.next_cursor
    ? `/leads?${new URLSearchParams({ ...Object.fromEntries(filterQuery), cursor: page.data.next_cursor })}`
    : null;

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageHeader title="Leads" description="Every prospect in your organization, with source and status." />
        <div className="flex flex-wrap gap-2">
          {can("leads:export") && (
            <a
              href={exportHref}
              className="inline-flex h-9 items-center rounded-md border border-border px-3 text-sm hover:bg-surface-raised"
            >
              Export CSV
            </a>
          )}
          {can("leads:import") && (
            <Link
              href="/leads/import"
              className="inline-flex h-9 items-center rounded-md border border-border px-3 text-sm hover:bg-surface-raised"
            >
              Import CSV
            </Link>
          )}
          {can("leads:write") && (
            <Link
              href="/leads/new"
              className="inline-flex h-9 items-center rounded-md bg-accent px-4 text-sm font-medium text-accent-fg hover:bg-accent-strong"
            >
              New lead
            </Link>
          )}
        </div>
      </div>

      <LeadFilters members={members} />

      {sp.import_id && (
        <Alert tone="info" className="mb-4">
          Showing leads created by one import.{" "}
          <Link href="/leads" className="underline">
            Show all leads
          </Link>
        </Alert>
      )}

      {!page.ok ? (
        <Alert tone="error">Could not load leads: {page.message}</Alert>
      ) : (
        <>
          <LeadsTable
            orgId={org.organization_id}
            leads={page.data.items}
            total={page.data.total}
            members={members}
            canWrite={can("leads:write")}
            canDelete={can("leads:delete")}
            filtered={PASSTHROUGH.some((k) => k !== "sort" && sp[k])}
          />
          <nav aria-label="Pagination" className="mt-4 flex items-center justify-between text-sm">
            <span className="text-fg-muted">
              {formatNumber(page.data.total)} {page.data.total === 1 ? "lead" : "leads"}
            </span>
            <span className="flex gap-2">
              {sp.cursor && (
                <Link
                  href={`/leads?${filterQuery}`}
                  className="rounded-md border border-border px-3 py-1.5 hover:bg-surface-raised"
                >
                  First page
                </Link>
              )}
              {nextHref && (
                <Link href={nextHref} className="rounded-md border border-border px-3 py-1.5 hover:bg-surface-raised">
                  Next page
                </Link>
              )}
            </span>
          </nav>
        </>
      )}
    </>
  );
}
