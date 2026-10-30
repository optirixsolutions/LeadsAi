import type { Metadata } from "next";

import { Alert } from "@/components/ui/alert";
import { TokenManager } from "@/features/agents/token-manager";
import type { McpToken } from "@/lib/agents";
import { orgGet } from "@/lib/org-api";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "MCP tokens" };

export default async function TokensPage() {
  const { org } = await requireOrg();
  const tokens = await orgGet<McpToken[]>(org.organization_id, "/mcp-tokens");
  if (!tokens.ok) return <Alert tone="error">Could not load tokens: {tokens.message}</Alert>;
  return (
    <TokenManager
      orgId={org.organization_id}
      tokens={tokens.data}
      canWrite={hasPermission(org.permissions, "leads:write")}
    />
  );
}
