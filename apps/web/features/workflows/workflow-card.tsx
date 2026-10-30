"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/format";
import { isActive, parseUrls, shouldPoll, type WorkflowRun } from "@/lib/workflows";

import { RunBadge } from "./run-badge";

const POLL_MS = 3000;
const MAX_URLS = 3;

export function WorkflowCard({
  orgId,
  leadId,
  latest,
  companyDomain,
  canRun,
}: {
  orgId: string;
  leadId: string;
  latest: WorkflowRun | null;
  companyDomain: string | null;
  canRun: boolean;
}) {
  const router = useRouter();
  const [run, setRun] = useState(latest);
  const [urls, setUrls] = useState("");
  const [propose, setPropose] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const polling = run ? shouldPoll(run.status) : false;
  const runId = run?.id;

  useEffect(() => {
    if (!polling || !runId) return;
    const timer = setInterval(async () => {
      const r = await apiRequest<WorkflowRun>(`/organizations/${orgId}/workflows/${runId}`);
      if (!r.ok) {
        setError(r.message);
        return;
      }
      setRun(r.data);
      // The run has written new results, which the panels below read from the server.
      if (!shouldPoll(r.data.status)) router.refresh();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [polling, runId, orgId, router]);

  const start = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const list = parseUrls(urls);
    if (list.length > MAX_URLS) return setError(`Enter at most ${MAX_URLS} page addresses.`);
    setBusy(true);
    const r = await apiRequest<WorkflowRun>(`/organizations/${orgId}/leads/${leadId}/workflows`, {
      method: "POST",
      body: { urls: list, propose_status: propose },
    });
    setBusy(false);
    if (!r.ok) return setError(r.message);
    setRun(r.data);
    setUrls("");
  };

  return (
    <Card>
      <CardHeader
        title="Research and qualification"
        description="Fetches pages, scores the lead, and writes a brief in the background, with every step recorded."
      />
      <div className="space-y-4 px-5 py-4 text-sm">
        {error && <Alert tone="error">{error}</Alert>}
        {run && (
          <div className="flex flex-wrap items-center gap-3" data-testid="latest-run">
            <RunBadge status={run.status} />
            <span className="text-xs text-fg-subtle">{formatDateTime(run.created_at)}</span>
            <Link href={`/workflows/${run.id}`} className="ml-auto text-xs text-accent hover:underline">
              View run
            </Link>
          </div>
        )}
        {run?.status === "failed" && run.error_message && <Alert tone="error">{run.error_message}</Alert>}
        {run?.status === "waiting_approval" && (
          <Alert tone="warning">This run is waiting for a manager or admin to approve a status change.</Alert>
        )}
        {canRun && !(run && isActive(run.status)) && (
          <form onSubmit={start} className="space-y-3" noValidate>
            {companyDomain && (
              <div>
                <label htmlFor="workflow-urls" className="mb-1.5 block text-xs font-medium text-fg-muted">
                  Pages to fetch first (optional)
                </label>
                <textarea
                  id="workflow-urls"
                  rows={2}
                  value={urls}
                  placeholder={`https://${companyDomain}/about`}
                  onChange={(e) => setUrls(e.target.value)}
                  className="w-full rounded-md border border-border bg-canvas px-3 py-2 text-sm text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none"
                />
                <p className="mt-1 text-xs text-fg-subtle">One per line, up to {MAX_URLS}, on {companyDomain} only.</p>
              </div>
            )}
            <label className="flex items-start gap-2 text-xs text-fg-muted">
              <input
                type="checkbox"
                checked={propose}
                onChange={(e) => setPropose(e.target.checked)}
                className="mt-0.5"
              />
              Propose a status change if the result is clear. A manager or admin must approve it first.
            </label>
            <Button type="submit" variant="secondary" size="sm" loading={busy}>
              Run workflow
            </Button>
          </form>
        )}
      </div>
    </Card>
  );
}
