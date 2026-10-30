"use client";

import { clsx } from "clsx";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Card, CardHeader } from "@/components/ui/card";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/format";
import { PROBLEM_LABELS } from "@/lib/intelligence";
import { AGENT_LABELS, agentFailure, TOOL_CALL_LABELS, type AgentRunDetail } from "@/lib/agents";

import { AgentBadge } from "./agent-badge";

const POLL_MS = 2000;

export function AgentRunView({ orgId, initial }: { orgId: string; initial: AgentRunDetail }) {
  const [run, setRun] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const running = run.status === "running";

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(async () => {
      const r = await apiRequest<AgentRunDetail>(`/organizations/${orgId}/agent-runs/${run.id}`);
      if (r.ok) setRun(r.data);
      else setError(r.message);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [running, orgId, run.id]);

  // Citations show a number, and the list of sources below uses the same one.
  const sourceIds = Object.keys(run.sources);
  const numberOf = (id: string) => sourceIds.indexOf(id) + 1;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <AgentBadge status={run.status} />
        <span className="text-sm text-fg-muted">{AGENT_LABELS[run.role] ?? run.role}</span>
        {run.lead_id && (
          <Link href={`/leads/${run.lead_id}`} className="text-sm text-accent hover:underline">
            View lead
          </Link>
        )}
        <Link href={`/workflows/${run.workflow_run_id}`} className="text-sm text-accent hover:underline">
          View workflow
        </Link>
      </div>

      {error && <Alert tone="error">{error}</Alert>}
      {running && (
        <Alert tone="info">This agent is queued or working. Local models can take a minute to start.</Alert>
      )}
      {run.status === "failed" && <Alert tone="error">{agentFailure(run.failure_category)}</Alert>}
      {run.status === "rejected" && (
        <Alert tone="warning">The agent answered, but none of its claims passed the review, so nothing is shown as fact.</Alert>
      )}
      {run.review_notes.length > 0 && (
        <Alert tone="warning">
          <ul className="list-disc space-y-1 pl-4">
            {run.review_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </Alert>
      )}

      {(run.summary || run.claims.length > 0) && (
        <Card>
          <CardHeader title="Findings" description="Written by a model and checked against its sources. Treat as inference." />
          <div className="space-y-3 px-5 py-4 text-sm">
            {run.summary && <p>{run.summary}</p>}
            <ul className="space-y-1.5">
              {run.claims.map((claim, i) => (
                <li key={i}>
                  {claim.text}
                  {claim.evidence_ids.map((id) => (
                    <a
                      key={id}
                      href={`#source-${numberOf(id)}`}
                      aria-label={`Source ${numberOf(id)}`}
                      className="ml-1 inline-flex h-4 min-w-4 items-center justify-center rounded border border-border px-1 text-[10px] text-fg-muted hover:border-accent hover:text-accent"
                    >
                      {numberOf(id)}
                    </a>
                  ))}
                </li>
              ))}
            </ul>
            {run.missing_information.length > 0 && (
              <div>
                <h3 className="text-xs font-medium text-fg-muted">Still unknown</h3>
                <ul className="mt-1 list-disc pl-4 text-fg-muted">
                  {run.missing_information.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Card>
      )}

      {run.rejected_claims.length > 0 && (
        <details className="text-xs text-fg-muted">
          <summary className="cursor-pointer">
            {run.rejected_claims.length} claim{run.rejected_claims.length === 1 ? "" : "s"} removed by the review
          </summary>
          <ul className="mt-2 space-y-1">
            {run.rejected_claims.map((claim, i) => (
              <li key={i}>
                {claim.text && (
                  <>
                    <span className="line-through">{claim.text}</span>{" "}
                  </>
                )}
                <span className="text-fg-subtle">({claim.problems.map((p) => PROBLEM_LABELS[p] ?? p).join(", ")})</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <Card>
        <CardHeader
          title="Tool calls"
          description={`${run.tool_call_count} call${run.tool_call_count === 1 ? "" : "s"} over ${run.model_turns} model turn${run.model_turns === 1 ? "" : "s"}. Refused calls are listed too.`}
        />
        {run.tool_calls.length === 0 ? (
          <p className="px-5 py-4 text-sm text-fg-muted">No tools have been called yet.</p>
        ) : (
          <ul className="divide-y divide-border">
            {run.tool_calls.map((call) => (
              <li key={call.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-2.5 text-sm">
                <code className="text-xs">{call.tool}</code>
                <span className="flex items-center gap-3 text-xs">
                  {call.error_category && <code className="text-fg-subtle">{call.error_category}</code>}
                  <span className={clsx(call.status === "ok" ? "text-fg-muted" : "text-danger")}>
                    {TOOL_CALL_LABELS[call.status] ?? call.status}
                  </span>
                  <time className="text-fg-subtle" dateTime={call.created_at}>
                    {formatDateTime(call.created_at)}
                  </time>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {sourceIds.length > 0 && (
        <Card>
          <CardHeader title="Sources it read" />
          <ol className="divide-y divide-border">
            {sourceIds.map((id, i) => (
              <li key={id} id={`source-${i + 1}`} className="scroll-mt-20 px-5 py-3 text-sm target:bg-surface-raised">
                <span className="mr-2 inline-flex h-4 min-w-4 items-center justify-center rounded border border-border px-1 text-[10px] text-fg-muted">
                  {i + 1}
                </span>
                {/* Rendered as text. Sources are untrusted, and nothing here is treated as markup. */}
                <span className="whitespace-pre-wrap break-words">{run.sources[id]}</span>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  );
}
