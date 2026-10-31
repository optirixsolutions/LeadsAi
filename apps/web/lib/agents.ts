import type { components } from "@salesiq/contracts";

export type AgentCatalog = components["schemas"]["CatalogOut"];
export type AgentInfo = components["schemas"]["AgentInfo"];
export type AgentRun = components["schemas"]["AgentRunOut"];
export type AgentRunDetail = components["schemas"]["AgentRunDetail"];
export type McpToken = components["schemas"]["TokenOut"];
export type McpTokenCreated = components["schemas"]["TokenCreated"];

export const AGENT_LABELS: Record<string, string> = {
  research: "Research agent",
  qualification: "Qualification agent",
  pipeline: "Pipeline analyst",
  outreach: "Outreach agent",
};

export const AGENT_STATUS_LABELS: Record<string, string> = {
  running: "Running",
  completed: "Finished",
  rejected: "Rejected by review",
  failed: "Failed",
};

export const AGENT_STATUS_TONES: Record<string, string> = {
  running: "border-sky-500/40 text-sky-300",
  completed: "border-accent/50 text-accent",
  rejected: "border-amber-500/40 text-amber-300",
  failed: "border-danger/40 text-danger",
};

export const AGENT_FAILURES: Record<string, string> = {
  unavailable: "The model server could not be reached. Check that it is running, then try again.",
  timeout: "The model took too long to answer. Try again in a moment.",
  model_not_found: "The configured model is not installed on the model server.",
  unsupported: "The configured model cannot use tools.",
  schema_invalid: "The model's final answer could not be read. Try again.",
  truncated: "The model ran out of output space before finishing. Try again.",
  cancelled: "This run was cancelled.",
  token_limit: "This run reached its token budget before it could answer.",
  time_limit: "This run reached its time limit before it could answer.",
  access_lost: "The person who started this run no longer has access.",
  attempts_exhausted: "Workers kept stopping before this run finished. Try again.",
};

export const TOOL_CALL_LABELS: Record<string, string> = {
  ok: "Ran",
  denied: "Refused",
  invalid: "Invalid",
  error: "Failed",
};

export function agentFailure(category: string | null | undefined): string {
  return AGENT_FAILURES[category ?? ""] ?? "This run could not finish. Try again.";
}

/** A token has one state a person cares about, in this order of importance. */
export function tokenState(token: Pick<McpToken, "revoked_at" | "expires_at">, now: Date): "revoked" | "expired" | "active" {
  if (token.revoked_at) return "revoked";
  return new Date(token.expires_at) <= now ? "expired" : "active";
}
