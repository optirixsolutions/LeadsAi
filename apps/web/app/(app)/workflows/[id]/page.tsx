import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { RunDetail } from "@/features/workflows/run-detail";
import { orgGet } from "@/lib/org-api";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";
import type { WorkflowRunDetail } from "@/lib/workflows";

export const metadata: Metadata = { title: "Workflow run" };

export default async function WorkflowRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { org } = await requireOrg();
  const orgId = org.organization_id;
  const run = await orgGet<WorkflowRunDetail>(orgId, `/workflows/${encodeURIComponent(id)}`);
  if (!run.ok) {
    if (run.status === 404 || run.status === 422) notFound();
    return <Alert tone="error">Could not load this run: {run.message}</Alert>;
  }
  return (
    <>
      <p className="mb-2 text-sm">
        <Link href="/workflows" className="text-fg-muted hover:text-fg">
          ← Workflows
        </Link>
      </p>
      <h1 className="mb-6 text-xl font-semibold tracking-tight">Workflow run</h1>
      <RunDetail
        key={run.data.id}
        orgId={orgId}
        initial={run.data}
        canRun={hasPermission(org.permissions, "workflows:run")}
        canDecide={hasPermission(org.permissions, "intelligence:review")}
      />
    </>
  );
}
