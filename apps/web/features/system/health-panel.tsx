import { Card, CardHeader } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-dot";
import { getReadiness } from "@/lib/api";

import { summarizeReadiness } from "./health";
import { RefreshButton } from "./refresh-button";

/** Server component: renders live readiness from the API on every request. */
export async function HealthPanel() {
  const summary = summarizeReadiness(await getReadiness());
  const checkedAt = new Date().toISOString().slice(11, 19);

  return (
    <Card>
      <CardHeader
        title="Platform health"
        description={`Checked ${checkedAt} UTC`}
        action={<RefreshButton />}
      />
      {summary.error && (
        <p role="alert" className="border-b border-border bg-danger/10 px-5 py-3 text-sm text-danger">
          {summary.error}. Start the API with <code className="font-mono">make api</code>.
        </p>
      )}
      <ul className="divide-y divide-border">
        {summary.components.map((c) => (
          <li key={c.name} className="flex items-center justify-between gap-4 px-5 py-3">
            <div>
              <p className="text-sm">{c.name}</p>
              <p className="text-xs text-fg-subtle">{c.detail}</p>
            </div>
            <StatusBadge health={c.health} />
          </li>
        ))}
      </ul>
    </Card>
  );
}
