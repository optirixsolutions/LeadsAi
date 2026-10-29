import type { ReadyResponse } from "@salesiq/contracts";

import type { ApiResult } from "@/lib/api-result";
import type { Health } from "@/components/ui/status-dot";

export interface ComponentHealth {
  name: string;
  health: Health;
  detail: string;
}

const LABELS: Record<string, string> = { database: "PostgreSQL", redis: "Redis" };

/** Derive the user-facing health of the API and each dependency from a readiness result. */
export function summarizeReadiness(result: ApiResult<ReadyResponse>): {
  overall: Health;
  components: ComponentHealth[];
  error?: string;
} {
  if (!result.ok) {
    return {
      overall: "down",
      components: [{ name: "API", health: "down", detail: result.message }],
      error: result.requestId ? `${result.message} (request ${result.requestId})` : result.message,
    };
  }
  const deps = Object.entries(result.data.dependencies).map(([key, d]) => ({
    name: LABELS[key] ?? key,
    health: (d.status === "ok" ? "ok" : "down") as Health,
    detail:
      d.status === "ok"
        ? `Responded in ${d.latency_ms ?? "?"} ms`
        : `Check failed (${d.error ?? "unknown error"})`,
  }));
  return {
    overall: deps.every((d) => d.health === "ok") ? "ok" : "degraded",
    components: [{ name: "API", health: "ok", detail: "Serving requests" }, ...deps],
  };
}
