import type { components } from "@salesiq/contracts";

export type WorkflowRun = components["schemas"]["WorkflowRunOut"];
export type WorkflowRunDetail = components["schemas"]["WorkflowRunDetail"];

export const RUN_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  waiting_approval: "Waiting for approval",
  succeeded: "Finished",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const RUN_TONES: Record<string, string> = {
  queued: "border-border text-fg-muted",
  running: "border-sky-500/40 text-sky-300",
  waiting_approval: "border-amber-500/40 text-amber-300",
  succeeded: "border-accent/50 text-accent",
  failed: "border-danger/40 text-danger",
  cancelled: "border-border text-fg-muted",
};

export const KIND_LABELS: Record<string, string> = {
  lead_intelligence: "Research and qualification",
  research: "Research brief",
  agent: "Agent run",
};

export const STEP_LABELS: Record<string, string> = {
  validate_request: "Check the request",
  load_context: "Load the ideal customer profile",
  gather_evidence: "Fetch requested pages",
  validate_sources: "Check evidence",
  score_lead: "Score the lead",
  interpret: "Write the research brief",
  run_agent: "Run the agent",
  quality_review: "Review the result",
  request_approval: "Wait for approval",
  apply_decision: "Apply the decision",
  finalize: "Finish",
};

export const STEP_STATUS_LABELS: Record<string, string> = {
  running: "Running",
  succeeded: "Done",
  failed: "Failed",
  interrupted: "Interrupted by a worker stopping",
  waiting: "Paused",
};

/** Runs that a person or a worker can still move forward. */
export function isActive(status: string): boolean {
  return status === "queued" || status === "running" || status === "waiting_approval";
}

/** Runs worth polling: their state can change without anyone here doing anything. */
export function shouldPoll(status: string): boolean {
  return status === "queued" || status === "running";
}

/** "qualified" -> "Qualified". Lead statuses are single lowercase words. */
export function statusWord(value: unknown): string {
  const text = String(value ?? "");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Up to three page addresses, one per line. Blank lines are ignored. */
export function parseUrls(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}
