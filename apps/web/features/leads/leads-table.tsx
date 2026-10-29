"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, EmptyState } from "@/components/ui/card";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { SelectField } from "@/components/ui/field";
import { LeadStatusBadge } from "@/components/ui/status-badge";
import { apiRequest } from "@/lib/client-api";
import { formatDate, LEAD_STATUSES, leadName, memberName, STATUS_LABELS, type Lead, type Member } from "@/lib/crm";

type BulkAction = "assign" | "set_status" | "add_tag" | "remove_tag" | "delete";

export function LeadsTable({
  orgId,
  leads,
  total,
  members,
  canWrite,
  canDelete,
  filtered,
}: {
  orgId: string;
  leads: Lead[];
  total: number;
  members: Member[];
  canWrite: boolean;
  canDelete: boolean;
  filtered: boolean;
}) {
  const router = useRouter();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [tag, setTag] = useState("");

  const allSelected = leads.length > 0 && leads.every((l) => selected.has(l.id));

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function bulk(action: BulkAction, value: string | null = null) {
    setBusy(true);
    setResult(null);
    const r = await apiRequest<{ affected: number }>(`/organizations/${orgId}/leads/bulk`, {
      method: "POST",
      body: { ids: [...selected], action, value },
    });
    setBusy(false);
    if (!r.ok) {
      setResult({ tone: "error", text: r.message });
      return;
    }
    setResult({ tone: "success", text: `Updated ${r.data.affected} of ${selected.size} selected leads.` });
    setSelected(new Set());
    router.refresh();
  }

  if (leads.length === 0) {
    return (
      <Card>
        <EmptyState
          title={filtered ? "No leads match these filters" : "No leads yet"}
          body={filtered ? "Try a different search or clear the filters." : "Create a lead or import a CSV to get started."}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {result && <Alert tone={result.tone}>{result.text}</Alert>}

      {canWrite && selected.size > 0 && (
        <div
          role="toolbar"
          aria-label="Bulk actions"
          className="flex flex-wrap items-end gap-2 rounded-[var(--radius-card)] border border-accent/40 bg-surface px-4 py-3"
        >
          <p className="mr-2 self-center text-sm">
            <strong>{selected.size}</strong> selected
          </p>
          <SelectField
            label="Set status"
            hideLabel
            value=""
            disabled={busy}
            onChange={(e) => e.target.value && bulk("set_status", e.target.value)}
            className="w-40"
          >
            <option value="">Set status…</option>
            {LEAD_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Assign owner"
            hideLabel
            value=""
            disabled={busy}
            onChange={(e) => e.target.value && bulk("assign", e.target.value === "none" ? null : e.target.value)}
            className="w-44"
          >
            <option value="">Assign to…</option>
            <option value="none">Unassigned</option>
            {members.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.display_name || m.email}
              </option>
            ))}
          </SelectField>
          <span className="inline-flex gap-1">
            <label htmlFor="bulk-tag" className="sr-only">
              Tag
            </label>
            <input
              id="bulk-tag"
              value={tag}
              onChange={(e) => setTag(e.target.value)}
              placeholder="tag"
              maxLength={50}
              className="h-9 w-28 rounded-md border border-border bg-canvas px-3 text-sm focus:border-accent focus:outline-none"
            />
            <Button variant="secondary" disabled={!tag.trim() || busy} onClick={() => bulk("add_tag", tag.trim())}>
              Add tag
            </Button>
            <Button variant="ghost" disabled={!tag.trim() || busy} onClick={() => bulk("remove_tag", tag.trim())}>
              Remove
            </Button>
          </span>
          {canDelete && (
            <ConfirmButton
              label="Delete"
              confirmLabel={`Delete ${selected.size}`}
              ariaLabel="Delete selected leads"
              onConfirm={() => bulk("delete")}
            />
          )}
          <Button variant="ghost" className="ml-auto" onClick={() => setSelected(new Set())}>
            Clear selection
          </Button>
        </div>
      )}

      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Leads, {total} total</caption>
          <thead className="text-left text-xs text-fg-subtle">
            <tr className="border-b border-border">
              {canWrite && (
                <th className="w-10 px-4 py-2">
                  <input
                    type="checkbox"
                    aria-label="Select all leads on this page"
                    checked={allSelected}
                    onChange={() => setSelected(allSelected ? new Set() : new Set(leads.map((l) => l.id)))}
                    className="accent-[var(--color-accent)]"
                  />
                </th>
              )}
              <th className="px-4 py-2 font-medium">Lead</th>
              <th className="hidden px-4 py-2 font-medium md:table-cell">Company</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="hidden px-4 py-2 font-medium lg:table-cell">Owner</th>
              <th className="hidden px-4 py-2 font-medium lg:table-cell">Source</th>
              <th className="hidden px-4 py-2 font-medium sm:table-cell">Added</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {leads.map((lead) => (
              <tr key={lead.id} className={selected.has(lead.id) ? "bg-accent/5" : "hover:bg-surface-raised/50"}>
                {canWrite && (
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      aria-label={`Select ${leadName(lead)}`}
                      checked={selected.has(lead.id)}
                      onChange={() => toggle(lead.id)}
                      className="accent-[var(--color-accent)]"
                    />
                  </td>
                )}
                <td className="max-w-64 px-4 py-3">
                  <Link href={`/leads/${lead.id}`} className="font-medium hover:text-accent">
                    {leadName(lead)}
                  </Link>
                  <p className="truncate text-xs text-fg-subtle">{[lead.title, lead.email].filter(Boolean).join(" · ")}</p>
                  {lead.tags.length > 0 && (
                    <p className="mt-1 flex flex-wrap gap-1">
                      {lead.tags.map((t) => (
                        <span key={t} className="rounded bg-surface-raised px-1.5 text-[11px] text-fg-muted">
                          {t}
                        </span>
                      ))}
                    </p>
                  )}
                </td>
                <td className="hidden px-4 py-3 text-fg-muted md:table-cell">{lead.company?.name ?? "—"}</td>
                <td className="px-4 py-3">
                  <LeadStatusBadge status={lead.status} />
                </td>
                <td className="hidden px-4 py-3 text-fg-muted lg:table-cell">{memberName(members, lead.owner_user_id)}</td>
                <td className="hidden px-4 py-3 text-fg-muted lg:table-cell">{lead.source ?? "—"}</td>
                <td className="hidden px-4 py-3 text-fg-muted sm:table-cell">{formatDate(lead.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
