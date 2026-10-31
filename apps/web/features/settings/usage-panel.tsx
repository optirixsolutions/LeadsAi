"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Card, CardHeader } from "@/components/ui/card";
import { SelectField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import { formatNumber } from "@/lib/format";
import { usedShare, type Usage } from "@/lib/integrations";

export function UsagePanel({ orgId, usage, canChange }: { orgId: string; usage: Usage; canChange: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  const change = async (plan: string) => {
    setError(null);
    const r = await apiRequest<Usage>(`/organizations/${orgId}/billing/development-plan`, { method: "POST", body: { plan } });
    if (!r.ok) return setError(r.message);
    router.refresh();
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title={`${usage.plan.label} plan`} description="Limits are enforced on the server. Monthly counts restart on the first of the month, in UTC." />
        <ul className="space-y-4 px-5 py-4">
          {usage.metrics.map((m) => {
            const share = usedShare(m);
            return (
              <li key={m.metric}>
                <div className="flex justify-between gap-3 text-xs">
                  <span className="text-fg-muted">{m.label}</span>
                  <span className="tabular-nums">
                    {formatNumber(m.used)}
                    {m.limit === null || m.limit === undefined ? " · no limit" : ` of ${formatNumber(m.limit)}`}
                  </span>
                </div>
                {share !== null && (
                  <div
                    className="mt-1 h-1.5 rounded-full bg-surface-raised"
                    role="progressbar"
                    aria-label={m.label}
                    aria-valuenow={Math.round(share * 100)}
                    aria-valuemin={0}
                    aria-valuemax={100}
                  >
                    {share > 0 && (
                      <div className={share >= 1 ? "h-full rounded-full bg-danger" : "h-full rounded-full bg-accent"} style={{ width: `${share * 100}%` }} />
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
        <p className="border-t border-border px-5 py-3 text-xs text-fg-subtle">
          {usage.estimated_cost_usd === null
            ? "No priced model has been used this month. Local models have no cost per token."
            : `Estimated model cost this month: $${usage.estimated_cost_usd.toFixed(2)}. This is an estimate from configured rates, not a bill.`}
        </p>
      </Card>
      <Card>
        <CardHeader title="Billing" />
        <div className="space-y-3 px-5 py-4 text-sm">
          {error && <Alert tone="error">{error}</Alert>}
          <p className="text-fg-muted">No payment provider is connected, so nothing here charges anyone.</p>
          {usage.development_billing && canChange && (
            <SelectField
              className="max-w-xs"
              label="Plan (development only)"
              value={usage.plan.key}
              onChange={(e) => change(e.target.value)}
            >
              {usage.plans.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </SelectField>
          )}
        </div>
      </Card>
    </div>
  );
}
