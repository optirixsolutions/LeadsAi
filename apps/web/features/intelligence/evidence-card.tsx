"use client";

import { clsx } from "clsx";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { TextField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/format";
import { FLAG_LABELS, SOURCE_LABELS, type Evidence } from "@/lib/intelligence";

function EvidenceRow({
  orgId,
  item,
  number,
  canReview,
}: {
  orgId: string;
  item: Evidence;
  number: number;
  canReview: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const review = async (status: "accepted" | "rejected") => {
    setBusy(status);
    setError(null);
    const r = await apiRequest<Evidence>(`/organizations/${orgId}/leads/${item.lead_id}/evidence/${item.id}`, {
      method: "PATCH",
      body: { status },
    });
    setBusy(null);
    if (!r.ok) return setError(r.message);
    router.refresh();
  };

  return (
    <li id={`evidence-${item.id}`} className="scroll-mt-20 px-5 py-3 text-sm target:bg-surface-raised">
      <div className="flex flex-wrap items-center gap-2 text-xs text-fg-subtle">
        <span className="inline-flex h-4 min-w-4 items-center justify-center rounded border border-border px-1 text-[10px]">
          {number}
        </span>
        <span>{SOURCE_LABELS[item.source_type] ?? item.source_type}</span>
        <span
          className={clsx(
            "rounded border px-1.5 text-[11px]",
            item.status === "accepted" && "border-border",
            item.status === "quarantined" && "border-danger/40 text-danger",
            item.status === "rejected" && "border-border line-through",
          )}
        >
          {item.status}
        </span>
        <time dateTime={item.observed_at}>{formatDateTime(item.observed_at)}</time>
        {item.source_url && (
          // Scheme validated server-side (http/https only).
          <a
            href={item.source_url}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="max-w-full truncate hover:text-accent"
          >
            {item.title ?? item.source_url} ↗
          </a>
        )}
      </div>
      {/* Rendered as text. Evidence is untrusted, and nothing here is treated as markup. */}
      <p className="mt-1 line-clamp-6 whitespace-pre-wrap break-words">{item.content}</p>
      {item.status === "quarantined" && (
        <div className="mt-2 rounded border border-danger/30 px-3 py-2 text-xs">
          <p className="text-fg-muted">
            Held back from scoring and models because this text{" "}
            {item.screen_flags.map((f) => FLAG_LABELS[f] ?? f).join(", ")}.
          </p>
          {canReview ? (
            <div className="mt-2 flex gap-2">
              <Button variant="secondary" size="sm" loading={busy === "accepted"} onClick={() => review("accepted")}>
                Release as evidence
              </Button>
              <Button variant="ghost" size="sm" loading={busy === "rejected"} onClick={() => review("rejected")}>
                Reject
              </Button>
            </div>
          ) : (
            <p className="mt-1 text-fg-subtle">A manager or admin can review it.</p>
          )}
          {error && (
            <div className="mt-2">
              <Alert tone="error">{error}</Alert>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function AddEvidence({
  orgId,
  leadId,
  companyDomain,
}: {
  orgId: string;
  leadId: string;
  companyDomain: string | null;
}) {
  const router = useRouter();
  const [note, setNote] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [fetchUrl, setFetchUrl] = useState("");
  const [busy, setBusy] = useState<"note" | "fetch" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const base = `/organizations/${orgId}/leads/${leadId}/evidence`;

  const after = (item: Evidence) => {
    setNotice(
      item.status === "quarantined"
        ? "Saved, but held back for review because it reads like instructions."
        : "Evidence saved.",
    );
    router.refresh();
  };

  const addNote = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);
    if (!note.trim()) return setError("Write what you found first.");
    setBusy("note");
    const r = await apiRequest<Evidence>(base, {
      method: "POST",
      body: { content: note, source_url: sourceUrl.trim() || null },
    });
    setBusy(null);
    if (!r.ok) return setError(r.message);
    setNote("");
    setSourceUrl("");
    after(r.data);
  };

  const fetchPage = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);
    if (!fetchUrl.trim()) return setError("Enter a page address first.");
    setBusy("fetch");
    const r = await apiRequest<Evidence>(`${base}/fetch`, { method: "POST", body: { url: fetchUrl.trim() } });
    setBusy(null);
    if (!r.ok) return setError(r.message);
    setFetchUrl("");
    after(r.data);
  };

  return (
    <div className="space-y-4 border-b border-border px-5 py-4">
      {error && <Alert tone="error">{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}
      <form onSubmit={addNote} className="space-y-3" noValidate>
        <div>
          <label htmlFor="evidence-note" className="mb-1.5 block text-xs font-medium text-fg-muted">
            Add a research finding
          </label>
          <textarea
            id="evidence-note"
            rows={3}
            maxLength={20000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="w-full rounded-md border border-border bg-canvas px-3 py-2 text-sm text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none"
          />
        </div>
        <TextField label="Source link (optional)" value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} />
        <Button type="submit" variant="secondary" size="sm" loading={busy === "note"}>
          Save finding
        </Button>
      </form>
      {companyDomain ? (
        <form onSubmit={fetchPage} className="space-y-3 border-t border-border pt-4" noValidate>
          <TextField
            label="Fetch a page from the company site"
            hint={`HTTPS pages on ${companyDomain} only. robots.txt is respected.`}
            placeholder={`https://${companyDomain}/about`}
            value={fetchUrl}
            onChange={(e) => setFetchUrl(e.target.value)}
          />
          <Button type="submit" variant="secondary" size="sm" loading={busy === "fetch"}>
            Fetch page
          </Button>
        </form>
      ) : (
        <p className="border-t border-border pt-4 text-xs text-fg-subtle">
          Add a company website under Company facts to fetch pages from it.
        </p>
      )}
    </div>
  );
}

export function EvidenceCard({
  orgId,
  leadId,
  evidence,
  evidenceNumbers,
  companyDomain,
  canWrite,
  canReview,
}: {
  orgId: string;
  leadId: string;
  evidence: Evidence[];
  evidenceNumbers: Map<string, number>;
  companyDomain: string | null;
  canWrite: boolean;
  canReview: boolean;
}) {
  return (
    <Card>
      <CardHeader title="Research evidence" description="Everything assessments and briefs may rely on" />
      {canWrite && <AddEvidence orgId={orgId} leadId={leadId} companyDomain={companyDomain} />}
      {evidence.length === 0 ? (
        <EmptyState title="No evidence yet" body="Findings and fetched pages appear here with their source." />
      ) : (
        <ul className="divide-y divide-border">
          {evidence.map((item) => (
            <EvidenceRow
              key={item.id}
              orgId={orgId}
              item={item}
              number={evidenceNumbers.get(item.id) ?? 0}
              canReview={canReview}
            />
          ))}
        </ul>
      )}
    </Card>
  );
}
