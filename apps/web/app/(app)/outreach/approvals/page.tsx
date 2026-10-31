import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { formatDateTime } from "@/lib/format";
import { orgGet } from "@/lib/org-api";
import { APPROVAL_STATUS_LABELS, type ApprovalItem } from "@/lib/outreach";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Approvals" };

function List({ items }: { items: ApprovalItem[] }) {
  return (
    <ul className="divide-y divide-border">
      {items.map((a) => (
        <li key={a.id}>
          <Link href={`/outreach/${a.draft_id}`} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm hover:bg-surface-raised">
            <span className="min-w-0 flex-1 truncate font-medium">{a.subject}</span>
            <span className="break-all text-xs text-fg-muted">{a.recipient}</span>
            {a.flags.length > 0 && <span className="text-xs text-amber-300">Flagged by the checks</span>}
            <span className="text-xs text-fg-subtle">{APPROVAL_STATUS_LABELS[a.status] ?? a.status}</span>
            <time className="text-xs text-fg-subtle" dateTime={a.created_at}>
              {formatDateTime(a.created_at)}
            </time>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export default async function ApprovalsPage() {
  const { org } = await requireOrg();
  const approvals = await orgGet<ApprovalItem[]>(org.organization_id, "/approvals");
  if (!approvals.ok) return <Alert tone="error">Could not load approvals: {approvals.message}</Alert>;
  const waiting = approvals.data.filter((a) => a.status === "pending");
  const past = approvals.data.filter((a) => a.status !== "pending");
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="Waiting for a decision"
          description={
            hasPermission(org.permissions, "outreach:approve")
              ? "Open one to read it, then approve or reject it."
              : "A manager or admin decides these."
          }
        />
        {waiting.length === 0 ? <EmptyState title="Nothing is waiting" body="Requests for approval appear here." /> : <List items={waiting} />}
      </Card>
      {past.length > 0 && (
        <Card>
          <CardHeader title="Decided" />
          <List items={past} />
        </Card>
      )}
    </div>
  );
}
