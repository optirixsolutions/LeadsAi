"use client";

import type { components } from "@salesiq/contracts";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/format";

type AuditPage = components["schemas"]["AuditPageOut"];
type Entry = AuditPage["items"][number];

const ACTION_LABELS: Record<string, string> = {
  "org.created": "Organization created",
  "org.updated": "Organization renamed",
  "invitation.created": "Invitation sent",
  "invitation.revoked": "Invitation revoked",
  "invitation.accepted": "Invitation accepted",
  "member.role_changed": "Member role changed",
  "member.removed": "Member removed",
  "member.left": "Member left",
};

function describe(e: Entry): string {
  const d = e.data as Record<string, unknown>;
  if (e.action === "member.role_changed") return `${String(d.from)} → ${String(d.to)}`;
  if (e.action === "invitation.created") return `${String(d.email)} as ${String(d.role)}`;
  if (e.action === "org.updated" && Array.isArray(d.name)) return `“${d.name[0]}” → “${d.name[1]}”`;
  return "";
}

export function AuditLog({ orgId, initial }: { orgId: string; initial: AuditPage }) {
  const [items, setItems] = useState(initial.items);
  const [cursor, setCursor] = useState(initial.next_cursor);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadMore() {
    if (!cursor) return;
    setLoading(true);
    setError(null);
    const r = await apiRequest<AuditPage>(
      `/organizations/${orgId}/audit?limit=25&cursor=${encodeURIComponent(cursor)}`,
    );
    setLoading(false);
    if (!r.ok) {
      setError(r.message);
      return;
    }
    setItems((prev) => [...prev, ...r.data.items]);
    setCursor(r.data.next_cursor);
  }

  return (
    <Card>
      <CardHeader title="Audit log" description="Security-relevant changes in this organization" />
      {items.length === 0 ? (
        <EmptyState title="No activity yet" body="Changes to members, invitations, and settings appear here." />
      ) : (
        <ul className="divide-y divide-border">
          {items.map((e) => (
            <li key={e.id} className="flex items-start justify-between gap-4 px-5 py-3 text-sm">
              <div className="min-w-0">
                <p>{ACTION_LABELS[e.action] ?? e.action}</p>
                {describe(e) && <p className="truncate text-xs text-fg-subtle">{describe(e)}</p>}
              </div>
              <time dateTime={e.created_at} className="shrink-0 text-xs text-fg-subtle">
                {formatDateTime(e.created_at)}
              </time>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <div className="px-5 pb-3">
          <Alert tone="error">{error}</Alert>
        </div>
      )}
      {cursor && (
        <div className="border-t border-border px-5 py-3">
          <Button variant="secondary" size="sm" onClick={loadMore} loading={loading}>
            Load more
          </Button>
        </div>
      )}
    </Card>
  );
}
