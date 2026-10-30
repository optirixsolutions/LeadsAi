"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { apiRequest } from "@/lib/client-api";
import type { AgentRun } from "@/lib/agents";

/** Starts a run and opens it. The run page follows its progress. */
export function StartAgent({
  orgId,
  role,
  label,
  leadId,
}: {
  orgId: string;
  role: string;
  label: string;
  leadId?: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setBusy(true);
    setError(null);
    const r = await apiRequest<AgentRun>(`/organizations/${orgId}/agents/${role}/runs`, {
      method: "POST",
      body: leadId ? { lead_id: leadId } : {},
    });
    if (!r.ok) {
      setBusy(false);
      return setError(r.message);
    }
    router.push(`/agents/${r.data.id}`);
  };

  return (
    <div className="space-y-2">
      <Button variant="secondary" size="sm" onClick={start} loading={busy}>
        {label}
      </Button>
      {error && <Alert tone="error">{error}</Alert>}
    </div>
  );
}
