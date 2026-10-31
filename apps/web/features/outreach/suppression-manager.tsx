"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { SelectField, TextField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import { formatDate } from "@/lib/format";
import { SUPPRESSION_REASON_LABELS, type Suppression } from "@/lib/outreach";

export function SuppressionManager({
  orgId,
  entries,
  canAdd,
  canRemove,
}: {
  orgId: string;
  entries: Suppression[];
  canAdd: boolean;
  canRemove: boolean;
}) {
  const router = useRouter();
  const [kind, setKind] = useState("email");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const base = `/organizations/${orgId}/outreach/suppressions`;

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return setError("Enter an address or domain.");
    setBusy(true);
    setError(null);
    const r = await apiRequest<Suppression>(base, { method: "POST", body: { kind, value } });
    setBusy(false);
    if (!r.ok) return setError(r.message);
    setValue("");
    router.refresh();
  };

  const remove = async (id: string) => {
    setError(null);
    const r = await apiRequest<null>(`${base}/${id}`, { method: "DELETE" });
    if (!r.ok) return setError(r.message);
    router.refresh();
  };

  return (
    <Card>
      <CardHeader
        title="Do not contact"
        description="Checked when a draft is written, when approval is requested, and again just before sending."
      />
      {error && (
        <div className="px-5 pt-4">
          <Alert tone="error">{error}</Alert>
        </div>
      )}
      {canAdd && (
        <form onSubmit={add} className="grid gap-4 px-5 py-4 sm:grid-cols-[10rem_1fr_auto] sm:items-end" noValidate>
          <SelectField label="Type" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="email">Email address</option>
            <option value="domain">Whole domain</option>
          </SelectField>
          <TextField label="Address or domain" value={value} maxLength={320} onChange={(e) => setValue(e.target.value)} />
          <Button type="submit" variant="secondary" loading={busy}>
            Add
          </Button>
        </form>
      )}
      {entries.length === 0 ? (
        <EmptyState title="Nobody on the list" body="People who opt out, and addresses a mail server refuses, are added here." />
      ) : (
        <ul className="divide-y divide-border border-t border-border">
          {entries.map((entry) => (
            <li key={entry.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
              <span className="min-w-0 break-all font-medium">{entry.value}</span>
              <span className="text-xs text-fg-subtle">
                {SUPPRESSION_REASON_LABELS[entry.reason] ?? entry.reason} · {formatDate(entry.created_at)}
              </span>
              {canRemove && entry.reason !== "opt_out" && (
                <span className="ml-auto">
                  <ConfirmButton
                    label="Remove"
                    confirmLabel={`Remove ${entry.value}`}
                    onConfirm={() => remove(entry.id)}
                  />
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
