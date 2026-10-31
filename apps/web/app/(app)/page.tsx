import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { HealthPanel } from "@/features/system/health-panel";
import {
  describeActivity,
  formatDateTime,
  formatNumber,
  formatTotals,
  LEAD_STATUSES,
  STATUS_LABELS,
  type Overview,
  type StageSummary,
} from "@/lib/crm";
import { attentionItems, type Attention } from "@/lib/analytics";
import { getMembers, orgGet } from "@/lib/org-api";
import { requireOrg } from "@/lib/session";

export const dynamic = "force-dynamic";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="px-5 py-4">
      <p className="text-xs text-fg-muted">{label}</p>
      <p className="mt-1 truncate text-2xl font-semibold tracking-tight tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-fg-subtle">{hint}</p>}
    </Card>
  );
}

export default async function OverviewPage() {
  const { org } = await requireOrg();
  const [overview, summary, members, attention] = await Promise.all([
    orgGet<Overview>(org.organization_id, "/analytics/overview"),
    orgGet<{ stages: StageSummary[] }>(org.organization_id, "/pipeline/summary"),
    getMembers(org.organization_id),
    orgGet<Attention>(org.organization_id, "/analytics/attention"),
  ]);
  const waiting = attention.ok ? attentionItems(attention.data) : [];

  return (
    <>
      <PageHeader
        title="Overview"
        description={`Pipeline and lead activity for ${org.organization_name}, computed from stored records.`}
      />
      {waiting.length > 0 && (
        <Card className="mb-6">
          <CardHeader title="Waiting on someone" />
          <ul className="divide-y divide-border">
            {waiting.map((item) => (
              <li key={item.key}>
                <Link href={item.href} className="flex items-center gap-3 px-5 py-2.5 text-sm hover:bg-surface-raised">
                  <span className="w-8 font-semibold tabular-nums">{formatNumber(item.count)}</span>
                  <span className="text-fg-muted">{item.label}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {!overview.ok ? (
        <Alert tone="error">Could not load metrics: {overview.message}</Alert>
      ) : overview.data.leads_total === 0 && overview.data.open_opportunities === 0 ? (
        <Card className="mb-6">
          <EmptyState
            title="No leads yet"
            body="Add or import leads to see qualification, pipeline value, and activity here."
          >
            <div className="flex justify-center gap-2">
              <Link
                href="/leads/new"
                className="inline-flex h-9 items-center rounded-md bg-accent px-4 text-sm font-medium text-accent-fg hover:bg-accent-strong"
              >
                Add a lead
              </Link>
              <Link
                href="/leads/import"
                className="inline-flex h-9 items-center rounded-md border border-border px-4 text-sm hover:bg-surface-raised"
              >
                Import CSV
              </Link>
            </div>
          </EmptyState>
        </Card>
      ) : (
        <OverviewMetrics overview={overview.data} stages={summary.ok ? summary.data.stages : []} members={members} />
      )}
      <div className="max-w-xl">
        <HealthPanel />
      </div>
    </>
  );
}

function OverviewMetrics({
  overview: o,
  stages,
  members,
}: {
  overview: Overview;
  stages: StageSummary[];
  members: Parameters<typeof describeActivity>[1];
}) {
  const maxStatus = Math.max(1, ...Object.values(o.leads_by_status));
  const openStages = stages.filter((s) => s.kind === "open");
  const maxStage = Math.max(1, ...openStages.map((s) => s.count));

  return (
    <div className="mb-6 space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat label="Leads" value={formatNumber(o.leads_total)} />
        <Stat label="Added, last 30 days" value={formatNumber(o.leads_added_30d)} />
        <Stat label="Qualified" value={formatNumber(o.leads_by_status.qualified ?? 0)} />
        <Stat
          label="Open pipeline"
          value={formatTotals(o.open_pipeline_value)}
          hint={`${o.open_opportunities} open ${o.open_opportunities === 1 ? "opportunity" : "opportunities"}`}
        />
        <Stat
          label="Won, last 90 days"
          value={formatTotals(o.won_value_90d)}
          hint={`${o.won_count_90d} closed won`}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader title="Leads by status" />
          <ul className="space-y-3 px-5 py-4">
            {LEAD_STATUSES.map((s) => {
              const n = o.leads_by_status[s] ?? 0;
              return (
                <li key={s}>
                  <Link href={`/leads?status=${s}`} className="group block">
                    <div className="flex justify-between text-xs">
                      <span className="text-fg-muted group-hover:text-fg">{STATUS_LABELS[s]}</span>
                      <span className="tabular-nums">{n}</span>
                    </div>
                    <div className="mt-1 h-1.5 rounded-full bg-surface-raised">
                      <div className="h-full rounded-full bg-accent" style={{ width: `${(n / maxStatus) * 100}%` }} />
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        </Card>

        <Card>
          <CardHeader title="Open pipeline by stage" />
          {openStages.every((s) => s.count === 0) ? (
            <EmptyState title="No open opportunities" body="Create opportunities from a lead's profile." />
          ) : (
            <ul className="space-y-3 px-5 py-4">
              {openStages.map((s) => (
                <li key={s.stage_id}>
                  <div className="flex justify-between gap-2 text-xs">
                    <span className="truncate text-fg-muted">{s.name}</span>
                    <span className="shrink-0 tabular-nums">
                      {s.count} · {formatTotals(s.totals)}
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-surface-raised">
                    <div className="h-full rounded-full bg-sky-400" style={{ width: `${(s.count / maxStage) * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader title="Recent activity" />
          {o.recent_activity.length === 0 ? (
            <EmptyState title="No activity yet" body="Changes to leads and opportunities appear here." />
          ) : (
            <ul className="divide-y divide-border">
              {o.recent_activity.map((a) => {
                const { title, detail } = describeActivity(a, members);
                return (
                  <li key={a.id} className="px-5 py-2.5 text-sm">
                    <div className="flex justify-between gap-3">
                      <span className="truncate">{title}</span>
                      <time dateTime={a.created_at} className="shrink-0 text-xs text-fg-subtle">
                        {formatDateTime(a.created_at)}
                      </time>
                    </div>
                    {detail && <p className="truncate text-xs text-fg-subtle">{detail}</p>}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
