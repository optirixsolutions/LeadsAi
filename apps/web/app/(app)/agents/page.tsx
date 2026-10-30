import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { AgentBadge } from "@/features/agents/agent-badge";
import { StartAgent } from "@/features/agents/start-agent";
import { AGENT_LABELS, type AgentCatalog, type AgentRun } from "@/lib/agents";
import { formatDateTime } from "@/lib/format";
import { orgGet } from "@/lib/org-api";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Agents" };

export default async function AgentsPage() {
  const { org } = await requireOrg();
  const orgId = org.organization_id;
  const [catalog, runs] = await Promise.all([
    orgGet<AgentCatalog>(orgId, "/agents"),
    orgGet<AgentRun[]>(orgId, "/agent-runs"),
  ]);
  const canRun = hasPermission(org.permissions, "workflows:run");

  return (
    <>
      <PageHeader
        title="Agents"
        description="Each has a narrow job, read-only tools, and hard limits. They cannot change your data."
      />
      {!catalog.ok ? (
        <Alert tone="error">Could not load agents: {catalog.message}</Alert>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          {catalog.data.agents.map((agent) => (
            <Card key={agent.role}>
              <CardHeader title={agent.label} />
              <div className="space-y-3 px-5 py-4 text-sm">
                <p className="text-fg-muted">{agent.description}</p>
                <div>
                  <p className="text-xs text-fg-subtle">Tools it can use</p>
                  <ul className="mt-1 flex flex-wrap gap-1">
                    {agent.tools.map((tool) => (
                      <li key={tool}>
                        <code className="rounded border border-border px-1 text-[11px] text-fg-muted">{tool}</code>
                      </li>
                    ))}
                  </ul>
                </div>
                <p className="text-xs text-fg-subtle">
                  At most {agent.max_tool_calls} tool calls and {agent.max_model_turns} model turns.
                </p>
                {agent.needs_lead ? (
                  <p className="text-xs text-fg-subtle">Start this one from a lead&apos;s page.</p>
                ) : (
                  canRun && <StartAgent orgId={orgId} role={agent.role} label={`Run ${agent.label.toLowerCase()}`} />
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      <div className="mt-6">
        <Card>
          <CardHeader title="Recent runs" />
          {!runs.ok ? (
            <div className="px-5 py-4">
              <Alert tone="error">Could not load runs: {runs.message}</Alert>
            </div>
          ) : runs.data.length === 0 ? (
            <EmptyState title="No runs yet" body="Start one above, or from a lead's page." />
          ) : (
            <ul className="divide-y divide-border">
              {runs.data.map((run) => (
                <li key={run.id}>
                  <Link
                    href={`/agents/${run.id}`}
                    className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm hover:bg-surface-raised"
                  >
                    <AgentBadge status={run.status} />
                    <span>{AGENT_LABELS[run.role] ?? run.role}</span>
                    <span className="text-xs text-fg-subtle">
                      {run.tool_call_count} tool call{run.tool_call_count === 1 ? "" : "s"}
                    </span>
                    <time className="ml-auto text-xs text-fg-subtle" dateTime={run.created_at}>
                      {formatDateTime(run.created_at)}
                    </time>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
