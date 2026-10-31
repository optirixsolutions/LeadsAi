import type { components } from "@salesiq/contracts";

export type AnalyticsReport = components["schemas"]["AnalyticsReport"];
export type Attention = components["schemas"]["Attention"];

export const WINDOWS = [7, 30, 90];

export const FIT_ORDER = [
  { key: "high", label: "High fit" },
  { key: "medium", label: "Medium fit" },
  { key: "low", label: "Low fit" },
  { key: "unscored", label: "Not scored yet" },
];

export const FIT_LABELS: Record<string, string> = {
  high: "High fit",
  medium: "Medium fit",
  low: "Low fit",
};

export function percent(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

/** `waiting_approval` reads as "Waiting approval". Used where no better label exists. */
export function categoryLabel(key: string): string {
  const words = key.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Nothing has ever happened here, as opposed to nothing in this period. */
export function isEmptyReport(r: AnalyticsReport): boolean {
  const total = (counts: Record<string, number>) => Object.values(counts).reduce((a, b) => a + b, 0);
  return (
    total(r.leads.by_status) === 0 &&
    total(r.outreach.drafts_by_status) === 0 &&
    total(r.workflows.by_status) === 0 &&
    r.pipeline.opened + r.pipeline.won + r.pipeline.lost === 0
  );
}

export interface AttentionItem {
  key: string;
  count: number;
  label: string;
  href: string;
}

/** Only what has something waiting, most pressing first: an unknown send could be a duplicate. */
export function attentionItems(a: Attention): AttentionItem[] {
  const one = (count: number, single: string, many: string) => (count === 1 ? single : many);
  const items: AttentionItem[] = [
    {
      key: "unknown",
      count: a.outcomes_unknown,
      label: one(a.outcomes_unknown, "email with an unknown outcome", "emails with an unknown outcome"),
      href: "/outreach?status=send_unknown",
    },
    {
      key: "approvals",
      count: a.approvals_waiting,
      label: one(a.approvals_waiting, "draft waiting for approval", "drafts waiting for approval"),
      href: "/outreach/approvals",
    },
    {
      key: "ready",
      count: a.drafts_ready_to_send,
      label: one(a.drafts_ready_to_send, "approved draft not sent yet", "approved drafts not sent yet"),
      href: "/outreach?status=approved",
    },
    {
      key: "waiting",
      count: a.workflows_waiting,
      label: one(a.workflows_waiting, "workflow waiting for a decision", "workflows waiting for a decision"),
      href: "/workflows",
    },
    {
      key: "failed",
      count: a.workflows_failed_7d,
      label: one(a.workflows_failed_7d, "workflow failed in the last 7 days", "workflows failed in the last 7 days"),
      href: "/workflows",
    },
  ];
  return items.filter((i) => i.count > 0);
}
