"use client";

import { clsx } from "clsx";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/format";
import {
  componentFill,
  FIT_LABELS,
  FIT_TONES,
  REVIEW_LABELS,
  type Assessment,
  type AssessmentDetail,
} from "@/lib/intelligence";

/** Citation chips jump to the stored evidence row further down the page. */
function Citations({ ids, numbers }: { ids: string[]; numbers: Map<string, number> }) {
  return (
    <>
      {ids.map((id) => (
        <a
          key={id}
          href={`#evidence-${id}`}
          aria-label={`Evidence ${numbers.get(id) ?? ""}`}
          className="ml-1 inline-flex h-4 min-w-4 items-center justify-center rounded border border-border px-1 text-[10px] text-fg-muted hover:border-accent hover:text-accent"
        >
          {numbers.get(id) ?? "?"}
        </a>
      ))}
    </>
  );
}

export function AssessmentCard({
  orgId,
  leadId,
  assessment,
  evidenceNumbers,
  hasIcp,
  canRun,
  canReview,
}: {
  orgId: string;
  leadId: string;
  assessment: AssessmentDetail | null;
  evidenceNumbers: Map<string, number>;
  hasIcp: boolean;
  canRun: boolean;
  canReview: boolean;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const run = async () => {
    setBusy("run");
    setError(null);
    const r = await apiRequest<AssessmentDetail>(`/organizations/${orgId}/leads/${leadId}/assessments`, {
      method: "POST",
    });
    setBusy(null);
    if (!r.ok) return setError(r.message);
    router.refresh();
  };

  const review = async (status: "approved" | "rejected") => {
    if (!assessment) return;
    setBusy(status);
    setError(null);
    const r = await apiRequest<Assessment>(`/organizations/${orgId}/assessments/${assessment.id}`, {
      method: "PATCH",
      body: { evaluation_status: status },
    });
    setBusy(null);
    if (!r.ok) return setError(r.message);
    router.refresh();
  };

  const a = assessment;
  return (
    <Card>
      <CardHeader
        title="Assessment"
        description="Ranks this lead against your ICP using stored evidence. It is not a probability of conversion."
        action={
          canRun &&
          hasIcp && (
            <Button variant="secondary" size="sm" onClick={run} loading={busy === "run"}>
              {a ? "Reassess" : "Assess lead"}
            </Button>
          )
        }
      />
      {error && (
        <div className="px-5 pt-4">
          <Alert tone="error">{error}</Alert>
        </div>
      )}
      {!hasIcp ? (
        <EmptyState
          title="No ideal customer profile yet"
          body="Leads are scored against your profile, so it has to exist first."
        >
          <Link href="/settings/icp" className="text-sm text-accent hover:underline">
            Set up the profile
          </Link>
        </EmptyState>
      ) : !a ? (
        <EmptyState title="Not assessed yet" body="Add research evidence below, then assess this lead." />
      ) : (
        <div className="space-y-5 px-5 py-4 text-sm">
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-3xl font-semibold tabular-nums" data-testid="lead-score">
              {a.score}
              <span className="text-sm font-normal text-fg-subtle"> / 100</span>
            </p>
            <span className={clsx("inline-flex h-5 items-center rounded border px-1.5 text-[11px] font-medium", FIT_TONES[a.fit])}>
              {FIT_LABELS[a.fit] ?? a.fit}
            </span>
            <span className="text-xs text-fg-muted">{REVIEW_LABELS[a.evaluation_status] ?? a.evaluation_status}</span>
            <span className="ml-auto text-xs text-fg-subtle">
              {a.model_version} · {formatDateTime(a.created_at)}
            </span>
          </div>

          {a.evaluation_status === "insufficient_evidence" && (
            <Alert tone="warning">
              There is no current research behind this score, only CRM fields. Add evidence before relying on it.
            </Alert>
          )}

          <ul className="grid gap-2 sm:grid-cols-2">
            {a.components.map((c) => (
              <li key={c.name}>
                <div className="flex justify-between text-xs">
                  <span className="text-fg-muted">{c.label}</span>
                  <span className="tabular-nums text-fg-subtle">
                    {c.points == null ? "not configured" : `${c.points > 0 ? "+" : ""}${c.points}`}
                  </span>
                </div>
                <div className="mt-1 h-1.5 rounded bg-surface-raised" aria-hidden>
                  <div
                    className={clsx("h-full rounded", c.name === "negative" ? "bg-danger" : "bg-accent")}
                    style={{ width: `${componentFill(c.raw)}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>

          <section>
            <h3 className="text-xs font-medium text-fg-muted">Why this score</h3>
            <ul className="mt-2 space-y-1">
              {a.reasons.map((r, i) => (
                <li key={i}>
                  {r.text}
                  <Citations ids={r.evidence_ids} numbers={evidenceNumbers} />
                </li>
              ))}
            </ul>
          </section>

          {a.positive_signals.length + a.negative_signals.length > 0 && (
            <section>
              <h3 className="text-xs font-medium text-fg-muted">Signals found in evidence</h3>
              <ul className="mt-2 space-y-2">
                {[...a.positive_signals, ...a.negative_signals].map((s, i) => (
                  <li key={i} className="rounded border border-border px-3 py-2">
                    <p className={clsx("text-xs font-medium", s.type === "negative" ? "text-danger" : "text-accent")}>
                      {s.type}: {s.keyword}
                      <Citations ids={[s.evidence_id]} numbers={evidenceNumbers} />
                    </p>
                    <p className="mt-1 text-xs text-fg-muted">“{s.snippet}”</p>
                    <p className="mt-1 text-[11px] text-fg-subtle">Counts until {formatDateTime(s.expires_at)}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {a.missing_information.length > 0 && (
            <section>
              <h3 className="text-xs font-medium text-fg-muted">Missing information</h3>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-fg-muted">
                {a.missing_information.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </section>
          )}

          {canReview && a.evaluation_status !== "approved" && a.evaluation_status !== "rejected" && (
            <div className="flex gap-2 border-t border-border pt-4">
              <Button variant="secondary" size="sm" loading={busy === "approved"} onClick={() => review("approved")}>
                Approve
              </Button>
              <Button variant="ghost" size="sm" loading={busy === "rejected"} onClick={() => review("rejected")}>
                Reject
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
