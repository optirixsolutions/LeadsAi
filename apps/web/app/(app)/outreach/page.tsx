import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Card, EmptyState } from "@/components/ui/card";
import { DraftBadge } from "@/features/outreach/draft-badge";
import { formatDateTime } from "@/lib/format";
import { orgGet } from "@/lib/org-api";
import { DRAFT_STATUS_LABELS, ORIGIN_LABELS, type Draft } from "@/lib/outreach";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Outreach" };

export default async function OutreachPage({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const { status: asked } = await searchParams;
  const status = asked && asked in DRAFT_STATUS_LABELS ? asked : null;
  const { org } = await requireOrg();
  const drafts = await orgGet<Draft[]>(org.organization_id, `/outreach/drafts${status ? `?status=${status}` : ""}`);
  if (!drafts.ok) return <Alert tone="error">Could not load drafts: {drafts.message}</Alert>;
  return (
    <Card>
      {status && (
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3 text-sm">
          <span className="text-fg-muted">Showing: {DRAFT_STATUS_LABELS[status]}</span>
          <Link href="/outreach" className="text-accent hover:underline">
            Show all
          </Link>
        </div>
      )}
      {drafts.data.length === 0 ? (
        <EmptyState
          title={status ? "No drafts like this" : "No drafts yet"}
          body={status ? "Nothing has this status right now." : "Open a lead to write one, or to have the outreach agent draft one."}
        />
      ) : (
        <ul className="divide-y divide-border">
          {drafts.data.map((d) => (
            <li key={d.id}>
              <Link href={`/outreach/${d.id}`} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm hover:bg-surface-raised">
                <DraftBadge status={d.status} />
                <span className="min-w-0 flex-1 truncate font-medium">{d.subject}</span>
                <span className="break-all text-xs text-fg-muted">{d.recipient}</span>
                <span className="text-xs text-fg-subtle">{ORIGIN_LABELS[d.origin] ?? d.origin}</span>
                <time className="text-xs text-fg-subtle" dateTime={d.created_at}>
                  {formatDateTime(d.created_at)}
                </time>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
