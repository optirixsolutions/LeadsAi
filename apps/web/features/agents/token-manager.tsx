"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { SelectField, TextField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import { formatDate } from "@/lib/format";
import { tokenState, type McpToken, type McpTokenCreated } from "@/lib/agents";

export function TokenManager({
  orgId,
  tokens,
  canWrite,
}: {
  orgId: string;
  tokens: McpToken[];
  /** A role that can only read gets nothing from a write token, so it is not offered. */
  canWrite: boolean;
}) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [scope, setScope] = useState("read");
  const [days, setDays] = useState("30");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<McpTokenCreated | null>(null);
  const [now] = useState(() => new Date());
  const base = `/organizations/${orgId}/mcp-tokens`;

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setCreated(null);
    if (!name.trim()) return setError("Give the token a name, so you can recognize it later.");
    if (scope === "write" && !password) return setError("Enter your current password to create a token that can write.");
    setBusy(true);
    const r = await apiRequest<McpTokenCreated>(base, {
      method: "POST",
      body: { name, scope, expires_in_days: Number(days), current_password: scope === "write" ? password : null },
    });
    setBusy(false);
    if (!r.ok) return setError(r.message);
    setCreated(r.data);
    setName("");
    setPassword("");
    router.refresh();
  };

  const revoke = async (id: string) => {
    setError(null);
    const r = await apiRequest<null>(`${base}/${id}`, { method: "DELETE" });
    if (!r.ok) return setError(r.message);
    router.refresh();
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="MCP access tokens"
          description="Connect an MCP client to your data. A token never does more than your role allows at the moment it is used."
        />
        <form onSubmit={create} className="grid gap-4 px-5 py-4 sm:grid-cols-3" noValidate>
          <TextField label="Name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
          <SelectField label="Access" value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="read">Read only</option>
            {canWrite && <option value="write">Read and write</option>}
          </SelectField>
          <SelectField label="Expires in" value={days} onChange={(e) => setDays(e.target.value)}>
            <option value="7">7 days</option>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
          </SelectField>
          {scope === "write" && (
            <TextField
              label="Current password"
              type="password"
              autoComplete="current-password"
              hint="Needed because this token can change data."
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
          <p className="text-xs text-fg-subtle sm:col-span-3">
            Run the server with <code className="font-mono">python -m app.mcp.http</code>, then point your client at{" "}
            <code className="font-mono">/mcp</code> on that server, sending the token as a bearer token. Changing your password
            or leaving this organization revokes your tokens.
          </p>
          <div className="sm:col-span-3">
            <Button type="submit" variant="secondary" size="sm" loading={busy}>
              Create token
            </Button>
          </div>
        </form>
        {(error || created) && (
          <div className="space-y-3 px-5 pb-4">
            {error && <Alert tone="error">{error}</Alert>}
            {created && (
              <Alert tone="success">
                <p>Copy this now. It will not be shown again.</p>
                <code className="mt-1 block break-all font-mono text-xs" data-testid="new-token">
                  {created.secret}
                </code>
              </Alert>
            )}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader title="Your tokens" />
        {tokens.length === 0 ? (
          <EmptyState title="No tokens yet" body="Tokens you create appear here." />
        ) : (
          <ul className="divide-y divide-border">
            {tokens.map((token) => {
              const state = tokenState(token, now);
              return (
                <li key={token.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{token.name}</p>
                    <p className="text-xs text-fg-subtle">
                      {token.scope === "write" ? "Read and write" : "Read only"} ·{" "}
                      {state === "active" ? `expires ${formatDate(token.expires_at)}` : state} ·{" "}
                      {token.last_used_at ? `last used ${formatDate(token.last_used_at)}` : "never used"}
                    </p>
                  </div>
                  {state === "active" && (
                    <ConfirmButton
                      label="Revoke"
                      confirmLabel={`Revoke ${token.name}`}
                      onConfirm={() => revoke(token.id)}
                    />
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}
