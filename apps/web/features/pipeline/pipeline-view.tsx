"use client";

import { clsx } from "clsx";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Card, EmptyState } from "@/components/ui/card";
import { SelectField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import {
  formatDate,
  formatMoney,
  formatTotals,
  memberName,
  type Member,
  type Opportunity,
  type Stage,
  type StageSummary,
} from "@/lib/crm";

interface Props {
  orgId: string;
  view: "board" | "table";
  stages: Stage[];
  allStages: Stage[];
  opportunities: Opportunity[];
  summary: StageSummary[];
  members: Member[];
  canMove: boolean;
  highlight?: string;
}

export function PipelineView(props: Props) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [moving, setMoving] = useState<string | null>(null);

  async function move(opp: Opportunity, stageId: string) {
    if (stageId === opp.stage_id) return;
    setMoving(opp.id);
    setError(null);
    const r = await apiRequest(`/organizations/${props.orgId}/opportunities/${opp.id}`, {
      method: "PATCH",
      body: { stage_id: stageId },
    });
    setMoving(null);
    if (!r.ok) setError(r.message);
    router.refresh();
  }

  if (props.opportunities.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No opportunities in the pipeline"
          body="Open a lead and choose “New opportunity” when it shows buying intent."
        >
          <Link href="/leads" className="text-sm text-accent hover:underline">
            Go to leads
          </Link>
        </EmptyState>
      </Card>
    );
  }

  const stageSelect = (opp: Opportunity) =>
    props.canMove ? (
      <SelectField
        label={`Stage for ${opp.name}`}
        hideLabel
        value={opp.stage_id}
        disabled={moving === opp.id}
        onChange={(e) => move(opp, e.target.value)}
        className="w-full"
      >
        {props.allStages.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </SelectField>
    ) : null;

  return (
    <div className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      {props.view === "table" ? (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-fg-subtle">
              <tr className="border-b border-border">
                <th className="px-4 py-2 font-medium">Opportunity</th>
                <th className="px-4 py-2 font-medium">Stage</th>
                <th className="px-4 py-2 text-right font-medium">Amount</th>
                <th className="hidden px-4 py-2 font-medium md:table-cell">Owner</th>
                <th className="hidden px-4 py-2 font-medium md:table-cell">Expected close</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {props.opportunities.map((o) => (
                <tr key={o.id} className={clsx(o.id === props.highlight && "bg-accent/5")}>
                  <td className="px-4 py-3">
                    <p className="font-medium">{o.name}</p>
                    {o.lead_id && (
                      <Link href={`/leads/${o.lead_id}`} className="text-xs text-fg-subtle hover:text-accent">
                        View lead
                      </Link>
                    )}
                  </td>
                  <td className="w-52 px-4 py-3">
                    {stageSelect(o) ?? props.allStages.find((s) => s.id === o.stage_id)?.name}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {o.amount != null ? formatMoney(o.amount, o.currency) : "—"}
                  </td>
                  <td className="hidden px-4 py-3 text-fg-muted md:table-cell">{memberName(props.members, o.owner_user_id)}</td>
                  <td className="hidden px-4 py-3 text-fg-muted md:table-cell">
                    {o.expected_close_date ? formatDate(o.expected_close_date) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : (
        <div className="-mx-4 flex gap-4 overflow-x-auto px-4 pb-2 md:mx-0 md:px-0" role="list" aria-label="Pipeline stages">
          {props.stages.map((stage) => {
            const cards = props.opportunities.filter((o) => o.stage_id === stage.id);
            const sum = props.summary.find((s) => s.stage_id === stage.id);
            return (
              <section
                key={stage.id}
                role="listitem"
                aria-label={stage.name}
                className="flex w-72 shrink-0 flex-col rounded-[var(--radius-card)] border border-border bg-surface"
              >
                <header className="border-b border-border px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="truncate text-sm font-medium">{stage.name}</h2>
                    <span className="rounded bg-surface-raised px-1.5 text-xs tabular-nums text-fg-muted">{cards.length}</span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-fg-subtle">{formatTotals(sum?.totals ?? {})}</p>
                </header>
                <ul className="flex-1 space-y-2 p-2">
                  {cards.length === 0 && <li className="px-2 py-6 text-center text-xs text-fg-subtle">Nothing here</li>}
                  {cards.map((o) => (
                    <li
                      key={o.id}
                      aria-label={o.name}
                      className={clsx(
                        "space-y-2 rounded-md border bg-canvas p-3",
                        o.id === props.highlight ? "border-accent" : "border-border",
                      )}
                    >
                      <div>
                        <p className="text-sm font-medium">{o.name}</p>
                        <p className="text-xs text-fg-subtle">
                          {o.amount != null ? formatMoney(o.amount, o.currency) : "No amount"}
                          {o.expected_close_date && ` · ${formatDate(o.expected_close_date)}`}
                        </p>
                        <p className="text-xs text-fg-subtle">{memberName(props.members, o.owner_user_id)}</p>
                      </div>
                      {stageSelect(o)}
                      {o.lead_id && (
                        <Link href={`/leads/${o.lead_id}`} className="block text-xs text-fg-muted hover:text-accent">
                          View lead →
                        </Link>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
