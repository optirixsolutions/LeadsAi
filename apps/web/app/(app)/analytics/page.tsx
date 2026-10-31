import { clsx } from "clsx";
import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { BarList, DailyBars } from "@/features/analytics/charts";
import { formatTotals, LEAD_STATUSES, STATUS_LABELS } from "@/lib/crm";
import { formatDateTime, formatNumber } from "@/lib/format";
import { AGENT_STATUS_LABELS } from "@/lib/agents";
import { categoryLabel, FIT_ORDER, isEmptyReport, percent, WINDOWS, type AnalyticsReport } from "@/lib/analytics";
import { orgGet } from "@/lib/org-api";
import { DELIVERY_STATUS_LABELS, DRAFT_STATUS_LABELS, SUPPRESSION_REASON_LABELS } from "@/lib/outreach";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Analytics" };

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="px-5 py-4">
      <p className="text-xs text-fg-muted">{label}</p>
      <p className="mt-1 truncate text-2xl font-semibold tracking-tight tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-fg-subtle">{hint}</p>}
    </Card>
  );
}

function toItems(counts: Record<string, number>, labels: Record<string, string>) {
  return Object.entries(counts)
    .map(([key, count]) => ({ key, label: labels[key] ?? categoryLabel(key), count }))
    .sort((a, b) => b.count - a.count);
}

export default async function AnalyticsPage({ searchParams }: { searchParams: Promise<{ days?: string }> }) {
  const { days: asked } = await searchParams;
  const days = WINDOWS.includes(Number(asked)) ? Number(asked) : 30;
  const { org } = await requireOrg();
  const report = await orgGet<AnalyticsReport>(org.organization_id, `/analytics/report?days=${days}`);

  return (
    <>
      <PageHeader title="Analytics" description="Counted from your stored records when you open this page. Nothing here is estimated or forecast." />
      <nav aria-label="Time range" className="mb-6 flex gap-1">
        {WINDOWS.map((w) => (
          <Link
            key={w}
            href={`/analytics?days=${w}`}
            aria-current={w === days ? "page" : undefined}
            className={clsx(
              "rounded-md border px-3 py-1.5 text-sm",
              w === days ? "border-accent/50 text-fg" : "border-border text-fg-muted hover:text-fg",
            )}
          >
            {w} days
          </Link>
        ))}
      </nav>
      {!report.ok ? (
        <Alert tone="error">Could not load analytics: {report.message}</Alert>
      ) : isEmptyReport(report.data) ? (
        <Card>
          <EmptyState title="Nothing to count yet" body="Add leads, run workflows, or write outreach, and the numbers appear here." />
        </Card>
      ) : (
        <Report report={report.data} />
      )}
    </>
  );
}

function Report({ report: r }: { report: AnalyticsReport }) {
  const accepted = r.outreach.deliveries_by_status.accepted ?? 0;
  const statusLabels: Record<string, string> = STATUS_LABELS;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat
          label="Win rate"
          value={r.pipeline.win_rate === null ? "—" : percent(r.pipeline.win_rate)}
          hint={`${r.pipeline.won} won, ${r.pipeline.lost} lost`}
        />
        <Stat label="Won value" value={formatTotals(r.pipeline.won_value)} hint={`${r.pipeline.opened} opened`} />
        <Stat label="Emails accepted by a mail server" value={formatNumber(accepted)} hint="Not proof they reached an inbox" />
        <Stat
          label="Median wait for approval"
          value={r.approvals.median_wait_hours === null ? "—" : `${r.approvals.median_wait_hours} h`}
          hint={`${r.approvals.waiting} waiting now`}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Leads" />
          <div className="space-y-6 px-5 py-4">
            <DailyBars label="Leads added" data={r.leads.added_by_day} />
            <BarList
              items={LEAD_STATUSES.map((s) => ({ key: s, label: statusLabels[s] ?? s, count: r.leads.by_status[s] ?? 0 }))}
            />
          </div>
        </Card>

        <Card>
          <CardHeader title="Fit against your ideal customer profile" description="Each lead's latest score, today. A score ranks a lead; it is not a chance of buying." />
          <div className="space-y-4 px-5 py-4">
            <BarList
              items={FIT_ORDER.map((f) => ({ key: f.key, label: f.label, count: r.leads.by_fit[f.key] ?? 0 }))}
            />
            <p className="text-xs text-fg-subtle">
              {formatNumber(r.leads.assessments_awaiting_review)} assessment
              {r.leads.assessments_awaiting_review === 1 ? "" : "s"} awaiting review.
            </p>
          </div>
        </Card>

        <Card>
          <CardHeader title="Outreach" />
          <div className="space-y-6 px-5 py-4">
            <DailyBars label="Emails accepted" data={r.outreach.accepted_by_day} />
            <div>
              <p className="mb-2 text-xs font-medium text-fg-muted">Send attempts in this period</p>
              {Object.keys(r.outreach.deliveries_by_status).length === 0 ? (
                <p className="text-xs text-fg-subtle">None.</p>
              ) : (
                <BarList items={toItems(r.outreach.deliveries_by_status, DELIVERY_STATUS_LABELS)} />
              )}
            </div>
            <div>
              <p className="mb-2 text-xs font-medium text-fg-muted">Drafts today</p>
              {Object.keys(r.outreach.drafts_by_status).length === 0 ? (
                <p className="text-xs text-fg-subtle">None.</p>
              ) : (
                <BarList items={toItems(r.outreach.drafts_by_status, DRAFT_STATUS_LABELS)} />
              )}
            </div>
            <div>
              <p className="mb-2 text-xs font-medium text-fg-muted">Do not contact, today</p>
              {Object.keys(r.outreach.suppressions_by_reason).length === 0 ? (
                <p className="text-xs text-fg-subtle">None.</p>
              ) : (
                <BarList items={toItems(r.outreach.suppressions_by_reason, SUPPRESSION_REASON_LABELS)} />
              )}
            </div>
            <p className="text-xs text-fg-subtle">
              In this period, {r.approvals.approved} approved and {r.approvals.rejected} rejected.
            </p>
          </div>
        </Card>

        <Card>
          <CardHeader title="Workflows and agents" />
          <div className="space-y-6 px-5 py-4">
            <div>
              <p className="mb-2 text-xs font-medium text-fg-muted">Runs started in this period</p>
              {Object.keys(r.workflows.by_status).length === 0 ? (
                <p className="text-xs text-fg-subtle">None.</p>
              ) : (
                <BarList items={toItems(r.workflows.by_status, {})} />
              )}
            </div>
            {r.workflows.failures.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-medium text-fg-muted">Why runs failed</p>
                <BarList
                  items={r.workflows.failures.map((f) => ({ key: f.category, label: categoryLabel(f.category), count: f.count }))}
                />
              </div>
            )}
            <div>
              <p className="mb-2 text-xs font-medium text-fg-muted">Agent runs</p>
              {Object.keys(r.workflows.agent_runs_by_status).length === 0 ? (
                <p className="text-xs text-fg-subtle">None.</p>
              ) : (
                <BarList items={toItems(r.workflows.agent_runs_by_status, AGENT_STATUS_LABELS)} />
              )}
            </div>
            <p className="text-xs text-fg-subtle">
              Successful runs took a median of {r.workflows.median_minutes === null ? "—" : `${r.workflows.median_minutes} min`}.{" "}
              {formatNumber(r.workflows.tool_calls)} tool calls, {formatNumber(r.workflows.tool_calls_refused)} refused.
            </p>
          </div>
        </Card>
      </div>
      <p className="text-xs text-fg-subtle">Counted {formatDateTime(r.generated_at)}. Days are in UTC.</p>
    </div>
  );
}
