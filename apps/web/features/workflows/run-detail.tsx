"use client";

import { clsx } from "clsx";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/format";
import {
  isActive,
  KIND_LABELS,
  shouldPoll,
  statusWord,
  STEP_LABELS,
  STEP_STATUS_LABELS,
  type WorkflowRun,
  type WorkflowRunDetail,
} from "@/lib/workflows";

import { RunBadge } from "./run-badge";

const POLL_MS = 2000;

export function RunDetail({
  orgId,
  initial,
  canRun,
  canDecide,
}: {
  orgId: string;
  initial: WorkflowRunDetail;
  canRun: boolean;
  canDecide: boolean;
}) {
  const router = useRouter();
  const [run, setRun] = useState(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const base = `/organizations/${orgId}/workflows/${run.id}`;
  const polling = shouldPoll(run.status);

  useEffect(() => {
    if (!polling) return;
    const timer = setInterval(async () => {
      const r = await apiRequest<WorkflowRunDetail>(base);
      if (r.ok) setRun(r.data);
      else setError(r.message);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [polling, base]);

  const act = async (name: string, path: string, body?: unknown) => {
    setBusy(name);
    setError(null);
    const r = await apiRequest<WorkflowRun>(`${base}/${path}`, { method: "POST", body });
    if (!r.ok) {
      setBusy(null);
      return setError(r.message);
    }
    const fresh = await apiRequest<WorkflowRunDetail>(base);
    setBusy(null);
    if (fresh.ok) setRun(fresh.data);
    router.refresh();
  };

  const request = run.approval_request;
  const result = run.result as {
    decision?: string;
    escalation_reasons?: string[];
    fetch_problems?: string[];
    usage?: { model?: string; input_tokens?: number; output_tokens?: number } | null;
  } | null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <RunBadge status={run.status} />
        <span className="text-sm text-fg-muted">{KIND_LABELS[run.kind] ?? run.kind}</span>
        <Link href={`/leads/${run.lead_id}`} className="text-sm text-accent hover:underline">
          View lead
        </Link>
        <div className="ml-auto flex gap-2">
          {canRun && run.resumable && (
            <Button size="sm" loading={busy === "resume"} onClick={() => act("resume", "resume")}>
              Resume
            </Button>
          )}
          {canRun && isActive(run.status) && !run.cancel_requested_at && (
            <ConfirmButton
              label="Cancel run"
              confirmLabel="Cancel this run"
              onConfirm={() => act("cancel", "cancel")}
            />
          )}
        </div>
      </div>

      {error && <Alert tone="error">{error}</Alert>}
      {run.status === "queued" && (
        <Alert tone="info">Waiting for a worker. If this stays queued, check System status to see whether one is running.</Alert>
      )}
      {run.cancel_requested_at && run.status === "running" && (
        <Alert tone="info">Cancelling. The run stops before its next step, once any model call under way returns.</Alert>
      )}
      {run.status === "failed" && (
        <Alert tone="error">
          <strong className="font-medium">Failed{run.current_step ? ` at “${STEP_LABELS[run.current_step] ?? run.current_step}”` : ""}.</strong>{" "}
          {run.error_message}
          {run.resumable && " Resuming continues from the last completed step, without repeating it."}
        </Alert>
      )}

      {run.status === "waiting_approval" && request && (
        <Card>
          <CardHeader title="Decision needed" description="Nothing changes on the lead until someone decides." />
          <div className="space-y-3 px-5 py-4 text-sm">
            <p>
              Change the lead&apos;s status from <strong className="font-medium">{statusWord(request.from)}</strong> to{" "}
              <strong className="font-medium">{statusWord(request.to)}</strong>, based on a score of {String(request.score)}{" "}
              ({String(request.fit)} fit). Deciding also approves or rejects that assessment.
            </p>
            {canDecide ? (
              <div className="flex gap-2">
                <Button
                  size="sm"
                  loading={busy === "approved"}
                  onClick={() => act("approved", "decision", { decision: "approved" })}
                >
                  Approve
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  loading={busy === "rejected"}
                  onClick={() => act("rejected", "decision", { decision: "rejected" })}
                >
                  Reject
                </Button>
              </div>
            ) : (
              <p className="text-xs text-fg-subtle">A manager or admin can decide this.</p>
            )}
          </div>
        </Card>
      )}

      {result && (
        <Card>
          <CardHeader
            title={result.decision === "escalated" ? "Finished, and needs a person's attention" : "Finished"}
          />
          <div className="space-y-3 px-5 py-4 text-sm">
            {(result.escalation_reasons ?? []).length > 0 && (
              <ul className="list-disc space-y-1 pl-4 text-fg-muted">
                {result.escalation_reasons?.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            )}
            {(result.fetch_problems ?? []).length > 0 && (
              <ul className="list-disc space-y-1 pl-4 text-xs text-fg-subtle">
                {result.fetch_problems?.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            )}
            {result.usage?.model && (
              <p className="text-xs text-fg-subtle">
                {result.usage.model} · {result.usage.input_tokens ?? "?"} input and {result.usage.output_tokens ?? "?"} output tokens
              </p>
            )}
          </div>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Steps"
          description={`Attempt ${run.attempts} of ${run.max_attempts} by a worker. Every try at a step is listed.`}
        />
        {run.steps.length === 0 ? (
          <p className="px-5 py-4 text-sm text-fg-muted">No steps have run yet.</p>
        ) : (
          <ol className="divide-y divide-border">
            {run.steps.map((step) => (
              <li key={step.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-2.5 text-sm">
                <span>{STEP_LABELS[step.name] ?? step.name}</span>
                <span className="flex items-center gap-3 text-xs">
                  {step.error_category && <code className="text-fg-subtle">{step.error_category}</code>}
                  <span
                    className={clsx(
                      step.status === "failed" && "text-danger",
                      step.status === "interrupted" && "text-amber-300",
                      step.status === "succeeded" && "text-fg-muted",
                      step.status === "running" && "text-sky-300",
                    )}
                  >
                    {STEP_STATUS_LABELS[step.status] ?? step.status}
                  </span>
                  <time className="text-fg-subtle" dateTime={step.started_at}>
                    {formatDateTime(step.started_at)}
                  </time>
                </span>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}
