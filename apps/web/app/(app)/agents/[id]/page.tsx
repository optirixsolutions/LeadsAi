import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { AgentRunView } from "@/features/agents/agent-run-view";
import type { AgentRunDetail } from "@/lib/agents";
import { orgGet } from "@/lib/org-api";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Agent run" };

export default async function AgentRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { org } = await requireOrg();
  const run = await orgGet<AgentRunDetail>(org.organization_id, `/agent-runs/${encodeURIComponent(id)}`);
  if (!run.ok) {
    if (run.status === 404 || run.status === 422) notFound();
    return <Alert tone="error">Could not load this run: {run.message}</Alert>;
  }
  return (
    <>
      <p className="mb-2 text-sm">
        <Link href="/agents" className="text-fg-muted hover:text-fg">
          ← Agents
        </Link>
      </p>
      <h1 className="mb-6 text-xl font-semibold tracking-tight">Agent run</h1>
      <AgentRunView key={run.data.id} orgId={org.organization_id} initial={run.data} />
    </>
  );
}
