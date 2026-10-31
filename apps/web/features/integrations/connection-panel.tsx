"use client";

import { clsx } from "clsx";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { TextField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/format";
import {
  connectionError,
  HEALTH_LABELS,
  HEALTH_TONES,
  type Connection,
  type ConnectionCreated,
} from "@/lib/integrations";

function NewSecret({ secret, path }: { secret: string; path: string }) {
  return (
    <Alert tone="success">
      <p className="font-medium">Copy this signing secret now. It will not be shown again.</p>
      <code data-testid="webhook-secret" className="mt-1 block break-all text-xs">
        {secret}
      </code>
      <p className="mt-2 text-xs">Your provider sends events to:</p>
      <code className="block break-all text-xs">{path}</code>
    </Alert>
  );
}

export function ConnectionPanel({
  orgId,
  connections,
  canManage,
  included,
}: {
  orgId: string;
  connections: Connection[];
  canManage: boolean;
  included: boolean;
}) {
  const router = useRouter();
  const [name, setName] = useState("Email provider");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("587");
  const [starttls, setStarttls] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [secret, setSecret] = useState<{ value: string; path: string } | null>(null);
  const base = `/organizations/${orgId}/integrations`;

  const connect = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!host.trim()) return setError("Enter the mail server's address.");
    setBusy("connect");
    setError(null);
    const r = await apiRequest<ConnectionCreated>(`${base}/email`, {
      method: "POST",
      body: { name, host, port: Number(port), starttls, username: username || null, password: password || null },
    });
    setBusy(null);
    if (!r.ok) return setError(r.message);
    setPassword("");
    setSecret({ value: r.data.webhook_secret, path: r.data.webhook_path });
    router.refresh();
  };

  const act = async (key: string, path: string, method: "POST" | "DELETE") => {
    setBusy(key);
    setError(null);
    const r = await apiRequest<{ webhook_secret?: string } | null>(path, { method });
    setBusy(null);
    if (!r.ok) return setError(r.message);
    router.refresh();
    return r.data;
  };

  return (
    <Card>
      <CardHeader
        title="Email provider"
        description="Any service that offers SMTP. Passwords are encrypted, and can be replaced but never read back."
      />
      <div className="space-y-4 px-5 py-4 text-sm">
        {error && <Alert tone="error">{error}</Alert>}
        {secret && (
          <div className="space-y-2">
            <NewSecret secret={secret.value} path={secret.path} />
            <Button variant="ghost" size="sm" onClick={() => setSecret(null)}>
              I have copied it
            </Button>
          </div>
        )}
        {connections.map((c) => (
          <div key={c.id} className="space-y-2 rounded-md border border-border p-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-medium">{c.name}</span>
              <span
                className={clsx(
                  "inline-flex h-5 items-center rounded border px-1.5 text-[11px] font-medium",
                  HEALTH_TONES[c.health] ?? HEALTH_TONES.unknown,
                )}
              >
                {HEALTH_LABELS[c.health] ?? c.health}
              </span>
              <span className="break-all text-xs text-fg-muted">
                {c.host}:{c.port}
              </span>
            </div>
            {c.last_error_category && <p className="text-danger">{connectionError(c.last_error_category)}</p>}
            <p className="text-xs text-fg-subtle">
              {c.has_password ? "Password stored, encrypted." : "No password stored."}
              {c.last_checked_at ? ` Last checked ${formatDateTime(c.last_checked_at)}.` : ""}
            </p>
            {!included && (
              <p className="text-fg-muted">Your plan does not include integrations, so this connection is not used.</p>
            )}
            {canManage && (
              <div className="flex flex-wrap gap-2">
                {included && (
                <>
                <Button
                  variant="secondary"
                  size="sm"
                  loading={busy === "check"}
                  onClick={() => act("check", `${base}/${c.id}/check`, "POST")}
                >
                  Check connection
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  loading={busy === "rotate"}
                  onClick={async () => {
                    const data = await act("rotate", `${base}/${c.id}/rotate-webhook-secret`, "POST");
                    if (data?.webhook_secret) setSecret({ value: data.webhook_secret, path: c.webhook_path });
                  }}
                >
                  New signing secret
                </Button>
                </>
                )}
                <ConfirmButton
                  label="Remove"
                  confirmLabel={`Remove ${c.name}`}
                  onConfirm={async () => {
                    const data = await act("remove", `${base}/${c.id}`, "DELETE");
                    if (data !== undefined) setSecret(null);
                  }}
                />
              </div>
            )}
          </div>
        ))}
        {connections.length === 0 && !included && (
          <p className="text-fg-muted">Your plan does not include integrations. See Settings → Plan and usage.</p>
        )}
        {connections.length === 0 && included && !canManage && (
          <p className="text-fg-muted">Nothing is connected. An owner or admin can connect a provider.</p>
        )}
        {connections.length === 0 && included && canManage && (
          <form onSubmit={connect} className="grid gap-4 sm:grid-cols-2" noValidate>
            <TextField label="Name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
            <TextField label="Mail server" placeholder="smtp.example.com" value={host} maxLength={253} onChange={(e) => setHost(e.target.value)} />
            <TextField label="Port" type="number" min={1} max={65535} value={port} onChange={(e) => setPort(e.target.value)} />
            <label className="flex items-center gap-2 self-end pb-2">
              <input type="checkbox" checked={starttls} onChange={(e) => setStarttls(e.target.checked)} />
              Use STARTTLS
            </label>
            <TextField label="Username" autoComplete="off" value={username} maxLength={320} onChange={(e) => setUsername(e.target.value)} />
            <TextField label="Password" type="password" autoComplete="new-password" value={password} maxLength={1024} onChange={(e) => setPassword(e.target.value)} />
            <div className="sm:col-span-2">
              <Button type="submit" size="sm" loading={busy === "connect"}>
                Connect
              </Button>
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}
