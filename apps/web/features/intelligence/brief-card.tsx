"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/format";
import { PROBLEM_LABELS, type Brief } from "@/lib/intelligence";

const POLL_MS = 3000;

const FAILURES: Record<string, string> = {
  unavailable: "The model server could not be reached. Check that it is running, then try again.",
  timeout: "The model took too long to answer. Try again in a moment.",
  model_not_found: "The configured model is not installed on the model server.",
  insufficient_resources: "The model server does not have enough memory for this model.",
  truncated: "The model ran out of output space before finishing. Try again.",
  schema_invalid: "The model returned something that could not be read. Try again.",
  stale: "This brief was interrupted before it finished. Try again.",
  busy: "The model is busy with other briefs. Try again in a moment.",
  lead_deleted: "This lead was deleted before the brief finished.",
};

export function BriefCard({
  orgId,
  leadId,
  initial,
  evidenceNumbers,
  canRequest,
}: {
  orgId: string;
  leadId: string;
  initial: Brief | null;
  evidenceNumbers: Map<string, number>;
  canRequest: boolean;
}) {
  const router = useRouter();
  const [brief, setBrief] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const base = `/organizations/${orgId}/leads/${leadId}/briefs`;
  const running = brief?.status === "running";

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(async () => {
      const r = await apiRequest<Brief>(`${base}/latest`);
      if (!r.ok) {
        setError(r.message);
        return;
      }
      setBrief(r.data);
      if (r.data.status !== "running") router.refresh();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [running, base, router]);

  const request = async () => {
    setBusy(true);
    setError(null);
    const r = await apiRequest<Brief>(base, { method: "POST" });
    setBusy(false);
    if (!r.ok) return setError(r.message);
    setBrief(r.data);
  };

  const b = brief;
  return (
    <Card>
      <CardHeader
        title="Research brief"
        description="Written by a model and checked against your evidence. It never changes the score."
        action={
          canRequest && (
            <Button variant="secondary" size="sm" onClick={request} loading={busy || running}>
              {running ? "Writing…" : b ? "Write again" : "Write brief"}
            </Button>
          )
        }
      />
      {error && (
        <div className="px-5 pt-4">
          <Alert tone="error">{error}</Alert>
        </div>
      )}
      {!b ? (
        <EmptyState title="No brief yet" body="A brief summarizes the accepted evidence, with citations." />
      ) : running ? (
        <p className="px-5 py-4 text-sm text-fg-muted" role="status">
          The model is writing this brief. Local models can take a minute to start.
        </p>
      ) : (
        <div className="space-y-4 px-5 py-4 text-sm">
          {b.status === "failed" && (
            <Alert tone="error">{FAILURES[b.failure_category ?? ""] ?? "The brief could not be written. Try again."}</Alert>
          )}
          {b.status === "rejected" && (
            <Alert tone="warning">The model answered, but none of its claims passed the evidence checks, so nothing is shown as fact.</Alert>
          )}
          {b.summary && <p>{b.summary}</p>}
          {b.claims.length > 0 && (
            <ul className="space-y-1.5">
              {b.claims.map((c, i) => (
                <li key={i}>
                  {c.text}
                  {c.evidence_ids.map((id) => (
                    <a
                      key={id}
                      href={`#evidence-${id}`}
                      aria-label={`Evidence ${evidenceNumbers.get(id) ?? ""}`}
                      className="ml-1 inline-flex h-4 min-w-4 items-center justify-center rounded border border-border px-1 text-[10px] text-fg-muted hover:border-accent hover:text-accent"
                    >
                      {evidenceNumbers.get(id) ?? "?"}
                    </a>
                  ))}
                </li>
              ))}
            </ul>
          )}
          {b.missing_information.length > 0 && b.status !== "failed" && (
            <div>
              <h3 className="text-xs font-medium text-fg-muted">Still unknown</h3>
              <ul className="mt-1 list-disc pl-4 text-fg-muted">
                {b.missing_information.map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ul>
            </div>
          )}
          {b.rejected_claims.length > 0 && (
            <details className="text-xs text-fg-muted">
              <summary className="cursor-pointer">
                {b.rejected_claims.length} claim{b.rejected_claims.length === 1 ? "" : "s"} removed by the checks
              </summary>
              <ul className="mt-2 space-y-1">
                {b.rejected_claims.map((c, i) => (
                  <li key={i}>
                    {c.text && (
                      <>
                        <span className="line-through">{c.text}</span>{" "}
                      </>
                    )}
                    <span className="text-fg-subtle">({c.problems.map((p) => PROBLEM_LABELS[p] ?? p).join(", ")})</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <p className="text-xs text-fg-subtle">
            {b.served_by ?? b.model_key} · prompt {b.prompt_version}
            {b.latency_ms != null && ` · ${(b.latency_ms / 1000).toFixed(1)} s`} · {formatDateTime(b.created_at)}
          </p>
        </div>
      )}
    </Card>
  );
}
