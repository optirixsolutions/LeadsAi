import type { components } from "@salesiq/contracts";

export type Connection = components["schemas"]["ConnectionOut"];
export type ConnectionCreated = components["schemas"]["ConnectionCreated"];
export type Integrations = components["schemas"]["IntegrationsOut"];
export type Usage = components["schemas"]["UsageOut"];
export type UsageMetric = components["schemas"]["UsageMetric"];

export const HEALTH_LABELS: Record<string, string> = {
  unknown: "Not checked yet",
  ok: "Working",
  failing: "Failing",
};

export const HEALTH_TONES: Record<string, string> = {
  unknown: "border-border text-fg-muted",
  ok: "border-accent/50 text-accent",
  failing: "border-danger/40 text-danger",
};

export const CONNECTION_ERRORS: Record<string, string> = {
  connection_failed: "Could not connect to this server.",
  session_failed: "The server would not start a session.",
  login_refused: "The server refused this username or password.",
  connection_host_refused: "This server's address or port is not allowed.",
  connection_needs_tls: "A server beyond this machine has to use STARTTLS.",
  external_not_allowed: "This server may not send beyond this machine.",
  credential_unreadable: "The stored password cannot be read. Enter it again.",
};

export const SERVER_BLOCKERS: Record<string, string> = {
  dispatch_disabled: "Sending is turned off on this server, so connected providers are not used yet.",
  external_not_allowed: "This server may only send to a mail server on this machine.",
};

export function connectionError(category: string | null | undefined): string {
  if (!category) return "";
  return CONNECTION_ERRORS[category] ?? "This connection is not working.";
}

/** How full a limit is, for a meter. No limit has no meter. */
export function usedShare(metric: Pick<UsageMetric, "used" | "limit">): number | null {
  if (metric.limit === null || metric.limit === undefined) return null;
  if (metric.limit === 0) return 1;
  return Math.min(1, metric.used / metric.limit);
}
