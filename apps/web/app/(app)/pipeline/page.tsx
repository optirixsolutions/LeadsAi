import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { PageHeader } from "@/components/ui/page-header";
import { PipelineView } from "@/features/pipeline/pipeline-view";
import type { Opportunity, StageSummary } from "@/lib/crm";
import { getMembers, getStages, orgGet } from "@/lib/org-api";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Pipeline" };

export default async function PipelinePage({
  searchParams,
}: {
  searchParams: Promise<{ view?: string; closed?: string; highlight?: string }>;
}) {
  const sp = await searchParams;
  const { org } = await requireOrg();
  const orgId = org.organization_id;
  const showClosed = sp.closed === "1";
  const view = sp.view === "table" ? "table" : "board";

  const [stages, opps, summary, members] = await Promise.all([
    getStages(orgId),
    orgGet<Opportunity[]>(orgId, `/opportunities?include_closed=${showClosed}`),
    orgGet<{ stages: StageSummary[] }>(orgId, "/pipeline/summary"),
    getMembers(orgId),
  ]);
  if (!stages.ok) return <Alert tone="error">Could not load stages: {stages.message}</Alert>;
  if (!opps.ok) return <Alert tone="error">Could not load opportunities: {opps.message}</Alert>;

  const link = (changes: Record<string, string | null>) => {
    const p = new URLSearchParams({ ...(view === "table" ? { view } : {}), ...(showClosed ? { closed: "1" } : {}) });
    for (const [k, v] of Object.entries(changes)) {
      if (v) p.set(k, v);
      else p.delete(k);
    }
    const qs = p.toString();
    return qs ? `/pipeline?${qs}` : "/pipeline";
  };
  const tab = (active: boolean) =>
    `rounded-md px-3 py-1.5 text-sm ${active ? "bg-surface-raised text-fg" : "text-fg-muted hover:text-fg"}`;

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageHeader title="Pipeline" description="Open opportunities by stage. Totals are per currency." />
        <div className="flex flex-wrap items-center gap-1 rounded-lg border border-border p-1">
          <Link href={link({ view: null })} className={tab(view === "board")} aria-current={view === "board" ? "page" : undefined}>
            Board
          </Link>
          <Link href={link({ view: "table" })} className={tab(view === "table")} aria-current={view === "table" ? "page" : undefined}>
            Table
          </Link>
          <span className="mx-1 h-5 w-px bg-border" aria-hidden />
          <Link href={link({ closed: showClosed ? null : "1" })} className={tab(showClosed)}>
            {showClosed ? "Hide closed" : "Show closed"}
          </Link>
        </div>
      </div>
      <PipelineView
        orgId={orgId}
        view={view}
        stages={stages.data.filter((s) => showClosed || s.kind === "open")}
        allStages={stages.data}
        opportunities={opps.data}
        summary={summary.ok ? summary.data.stages : []}
        members={members}
        canMove={hasPermission(org.permissions, "pipeline:write")}
        highlight={sp.highlight}
      />
    </>
  );
}
