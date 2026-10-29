import type { components } from "@salesiq/contracts";

import { formatMoney } from "./format";

export { formatDate, formatDateTime, formatMoney, formatNumber } from "./format";

export type Lead = components["schemas"]["LeadOut"];
export type LeadPage = components["schemas"]["LeadPage"];
export type LeadDetail = components["schemas"]["LeadDetailOut"];
export type Activity = components["schemas"]["ActivityOut"];
export type Opportunity = components["schemas"]["OpportunityOut"];
export type Stage = components["schemas"]["StageOut"];
export type StageSummary = components["schemas"]["StageSummary"];
export type Member = components["schemas"]["MemberOut"];
export type Overview = components["schemas"]["OverviewOut"];

export const LEAD_STATUSES = ["new", "contacted", "qualified", "disqualified"] as const;
export type LeadStatus = (typeof LEAD_STATUSES)[number];

export const STATUS_LABELS: Record<LeadStatus, string> = {
  new: "New",
  contacted: "Contacted",
  qualified: "Qualified",
  disqualified: "Disqualified",
};

export function leadName(lead: Pick<Lead, "first_name" | "last_name" | "email">): string {
  const name = [lead.first_name, lead.last_name].filter(Boolean).join(" ");
  return name || lead.email || "Unnamed lead";
}

/** Per-currency totals as one string, e.g. "$12,500 · €300". Never sums across currencies. */
export function formatTotals(totals: Record<string, string>): string {
  const entries = Object.entries(totals);
  if (entries.length === 0) return "—";
  return entries.map(([currency, amount]) => formatMoney(amount, currency)).join(" · ");
}

export function memberName(members: Member[], userId: string | null | undefined): string {
  if (!userId) return "Unassigned";
  const m = members.find((x) => x.user_id === userId);
  return m ? m.display_name || m.email : "Former member";
}

const ACTIVITY_LABELS: Record<string, string> = {
  created: "Lead created",
  imported: "Imported from CSV",
  updated: "Details updated",
  status_changed: "Status changed",
  assigned: "Owner changed",
  note: "Note",
  opportunity_created: "Opportunity created",
  stage_changed: "Stage changed",
  deleted: "Lead deleted",
};

export function describeActivity(a: Activity, members: Member[]): { title: string; detail: string } {
  const d = a.data as Record<string, unknown>;
  const title = ACTIVITY_LABELS[a.type] ?? a.type;
  switch (a.type) {
    case "status_changed":
      return {
        title,
        detail: `${STATUS_LABELS[d.from as LeadStatus] ?? d.from} → ${STATUS_LABELS[d.to as LeadStatus] ?? d.to}`,
      };
    case "assigned":
      return { title, detail: memberName(members, d.to as string | null) };
    case "updated":
      return { title, detail: Array.isArray(d.fields) ? (d.fields as string[]).join(", ").replaceAll("_", " ") : "" };
    case "stage_changed":
      return { title, detail: `${String(d.from)} → ${String(d.to)}` };
    case "opportunity_created":
      return { title, detail: `${String(d.name)} · ${String(d.stage)}` };
    case "note":
      return { title, detail: a.body ?? "" };
    default:
      return { title, detail: "" };
  }
}
