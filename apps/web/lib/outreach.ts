import type { components } from "@salesiq/contracts";

export type Draft = components["schemas"]["DraftOut"];
export type DraftDetail = components["schemas"]["DraftDetail"];
export type ApprovalItem = components["schemas"]["ApprovalListItem"];
export type Delivery = components["schemas"]["DeliveryOut"];
export type Suppression = components["schemas"]["SuppressionOut"];
export type OutreachSettings = components["schemas"]["OutreachSettingsView"];

export const DRAFT_STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  pending_approval: "Awaiting approval",
  approved: "Approved",
  sending: "Sending",
  sent: "Handed to mail server",
  undeliverable: "Undeliverable",
  send_unknown: "Outcome unknown",
  discarded: "Discarded",
};

export const DRAFT_STATUS_TONES: Record<string, string> = {
  draft: "border-border text-fg-muted",
  pending_approval: "border-amber-500/40 text-amber-300",
  approved: "border-accent/50 text-accent",
  sending: "border-sky-500/40 text-sky-300",
  sent: "border-accent/50 text-accent",
  undeliverable: "border-danger/40 text-danger",
  send_unknown: "border-danger/40 text-danger",
  discarded: "border-border text-fg-subtle",
};

export const ORIGIN_LABELS: Record<string, string> = {
  person: "Written by a person",
  agent: "Written by the outreach agent",
  mcp: "Written through an MCP client, which may be a model",
};

export const APPROVAL_STATUS_LABELS: Record<string, string> = {
  pending: "Waiting for a decision",
  approved: "Approved",
  rejected: "Rejected",
  superseded: "Replaced by an edit",
  expired: "Expired",
};

export const DELIVERY_STATUS_LABELS: Record<string, string> = {
  sending: "Sending",
  accepted: "Accepted by the mail server",
  failed: "Not sent",
  rejected: "Refused by the mail server",
  unknown: "Outcome unknown",
};

export const DELIVERY_ERRORS: Record<string, string> = {
  server_refused: "The mail server refused to take this, for a reason that is not about the address.",
  connection_failed: "Could not connect to the mail server.",
  session_failed: "The mail server would not start a session.",
  recipient_refused: "The mail server refused this address.",
  message_refused: "The mail server refused this message.",
  connection_lost: "The connection dropped while the message was going out.",
  interrupted: "The server stopped partway through sending.",
  adapter_error: "Sending failed unexpectedly.",
};

export const FLAG_LABELS: Record<string, string> = {
  unknown_citation: "The model cited a source that does not exist.",
  unsupported_number: "It contains a number the sources do not show.",
  low_support: "Little of this text matches the sources.",
  contains_contact: "It contains a link or address. Take it out before asking for approval. You can add your own.",
  instruction_like: "It reads like instructions and not like an email.",
};

export const SUPPRESSION_REASON_LABELS: Record<string, string> = {
  opt_out: "Opted out",
  bounced: "Refused by mail server",
  manual: "Added by a person",
};

export const OUTREACH_PERMISSIONS = {
  write: "outreach:write",
  send: "outreach:send",
  approve: "outreach:approve",
  configure: "outreach:configure",
} as const;

/** The one thing a person can do next, given where a draft stands. */
export function nextStep(status: string, needsEdit: boolean): string {
  if (status === "draft") {
    return needsEdit ? "Edit the flagged text, then ask for approval." : "Review the text, then ask for approval.";
  }
  if (status === "pending_approval") return "A manager or admin has to approve or reject this.";
  if (status === "approved") return "Ready to send, if nothing below stands in the way.";
  if (status === "send_unknown") return "Check the mail server's logs, then record what happened.";
  return "";
}
