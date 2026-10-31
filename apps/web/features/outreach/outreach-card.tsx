"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { TextField } from "@/components/ui/field";
import { StartAgent } from "@/features/agents/start-agent";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/format";
import type { Draft, DraftDetail } from "@/lib/outreach";

import { DraftBadge } from "./draft-badge";

/** A lead's outreach: what exists, and the two ways to start a draft. */
export function OutreachCard({
  orgId,
  leadId,
  email,
  drafts,
  canWrite,
  canRunAgent,
}: {
  orgId: string;
  leadId: string;
  email: string | null;
  drafts: Draft[];
  canWrite: boolean;
  canRunAgent: boolean;
}) {
  const router = useRouter();
  const [writing, setWriting] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!subject.trim() || !body.trim()) return setError("Write a subject and a message.");
    setBusy(true);
    setError(null);
    const r = await apiRequest<DraftDetail>(`/organizations/${orgId}/outreach/drafts`, {
      method: "POST",
      body: { lead_id: leadId, subject, body },
    });
    setBusy(false);
    if (!r.ok) return setError(r.message);
    router.push(`/outreach/${r.data.id}`);
  };

  return (
    <Card>
      <CardHeader title="Outreach" description="Nothing is sent until a manager or admin approves the exact text." />
      <div className="space-y-4 px-5 py-4 text-sm">
        {error && <Alert tone="error">{error}</Alert>}
        {drafts.length > 0 && (
          <ul className="divide-y divide-border rounded-md border border-border">
            {drafts.map((d) => (
              <li key={d.id}>
                <Link href={`/outreach/${d.id}`} className="flex flex-wrap items-center gap-3 px-3 py-2 hover:bg-surface-raised">
                  <DraftBadge status={d.status} />
                  <span className="min-w-0 flex-1 truncate">{d.subject}</span>
                  <time className="text-xs text-fg-subtle" dateTime={d.created_at}>
                    {formatDateTime(d.created_at)}
                  </time>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {!email ? (
          <p className="text-fg-muted">Add an email address to this lead to write to them.</p>
        ) : writing ? (
          <form onSubmit={create} className="space-y-3" noValidate>
            <TextField label="Subject" value={subject} maxLength={200} onChange={(e) => setSubject(e.target.value)} />
            <div>
              <label htmlFor="new-draft-body" className="mb-1.5 block text-xs font-medium text-fg-muted">
                Message
              </label>
              <textarea
                id="new-draft-body"
                rows={6}
                maxLength={5000}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                className="w-full resize-y rounded-md border border-border bg-canvas px-3 py-2 text-sm focus:border-accent focus:outline-none"
              />
            </div>
            <div className="flex gap-2">
              <Button type="submit" size="sm" loading={busy}>
                Save draft
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setWriting(false)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <div className="flex flex-wrap gap-2">
            {canWrite && (
              <Button variant="secondary" size="sm" onClick={() => setWriting(true)}>
                Write a draft
              </Button>
            )}
            {canWrite && canRunAgent && <StartAgent orgId={orgId} role="outreach" label="Run outreach agent" leadId={leadId} />}
          </div>
        )}
      </div>
    </Card>
  );
}
