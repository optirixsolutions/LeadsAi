import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Card, EmptyState } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { RunBadge } from "@/features/workflows/run-badge";
import { formatDateTime } from "@/lib/format";
import { orgGet } from "@/lib/org-api";
import { requireOrg } from "@/lib/session";
import { KIND_LABELS, STEP_LABELS, type WorkflowRun } from "@/lib/workflows";

export const metadata: Metadata = { title: "Workflows" };

export default async function WorkflowsPage() {
  const { org } = await requireOrg();
  const runs = await orgGet<WorkflowRun[]>(org.organization_id, "/workflows");

  return (
    <>
      <PageHeader title="Workflows" description="Background research and qualification runs, newest first." />
      {!runs.ok ? (
        <Alert tone="error">Could not load workflows: {runs.message}</Alert>
      ) : runs.data.length === 0 ? (
        <Card>
          <EmptyState title="No runs yet" body="Start one from a lead's page." />
        </Card>
      ) : (
        <Card>
          <ul className="divide-y divide-border">
            {runs.data.map((run) => (
              <li key={run.id}>
                <Link
                  href={`/workflows/${run.id}`}
                  className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm hover:bg-surface-raised"
                >
                  <RunBadge status={run.status} />
                  <span>{KIND_LABELS[run.kind] ?? run.kind}</span>
                  {run.status === "running" && run.current_step && (
                    <span className="text-xs text-fg-muted">{STEP_LABELS[run.current_step] ?? run.current_step}</span>
                  )}
                  {run.status === "failed" && run.error_message && (
                    <span className="min-w-0 truncate text-xs text-danger">{run.error_message}</span>
                  )}
                  <time className="ml-auto text-xs text-fg-subtle" dateTime={run.created_at}>
                    {formatDateTime(run.created_at)}
                  </time>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
