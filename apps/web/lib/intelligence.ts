import type { components } from "@salesiq/contracts";

export type Icp = components["schemas"]["IcpOut"];
export type IcpCreate = components["schemas"]["IcpCreate"];
export type Evidence = components["schemas"]["EvidenceOut"];
export type Assessment = components["schemas"]["AssessmentOut"];
export type AssessmentDetail = components["schemas"]["AssessmentDetail"];
export type Brief = components["schemas"]["BriefOut"];
export type CompanyDetail = components["schemas"]["CompanyDetailOut"];

export const FIT_LABELS: Record<string, string> = { high: "High fit", medium: "Medium fit", low: "Low fit" };

export const FIT_TONES: Record<string, string> = {
  high: "border-accent/50 text-accent",
  medium: "border-sky-500/40 text-sky-300",
  low: "border-border text-fg-muted",
};

export const REVIEW_LABELS: Record<string, string> = {
  pending_review: "Pending review",
  insufficient_evidence: "Insufficient evidence",
  approved: "Approved",
  rejected: "Rejected",
};

export const SOURCE_LABELS: Record<string, string> = {
  manual_note: "Research note",
  crm_record: "CRM record",
  fetched_page: "Fetched page",
};

export const FLAG_LABELS: Record<string, string> = {
  instruction_override: "tells the reader to ignore instructions",
  addressed_to_ai: "is addressed to an AI",
  score_manipulation: "tries to set a score or label",
  exfiltration: "asks someone to send data somewhere",
  hidden_characters: "contains invisible characters",
  mixed_script: "mixes lookalike letters from different alphabets",
};

export const PROBLEM_LABELS: Record<string, string> = {
  no_citation: "cites nothing",
  unknown_citation: "cites evidence it was not given",
  low_support: "not supported by what it cites",
  unsupported_number: "has a number that is not in its source",
  unsupported_contact: "has a link or address that is not in its source",
  instruction_like: "reads like instructions",
};

export const WEIGHT_FIELDS = [
  ["icp_fit", "ICP fit"],
  ["need", "Business need"],
  ["intent", "Buying intent"],
  ["timing", "Timing"],
  ["decision_maker", "Decision-maker relevance"],
  ["data_quality", "Data quality"],
] as const;

/** "Fintech, SaaS,, fintech" -> ["Fintech", "SaaS"]. The API applies the same rule. */
export function parseList(value: string): string[] {
  const seen = new Map<string, string>();
  for (const part of value.split(/[,\n]/)) {
    const term = part.trim();
    if (term && !seen.has(term.toLowerCase())) seen.set(term.toLowerCase(), term);
  }
  return [...seen.values()];
}

/** Whole numbers only; blank means "not set". Returns undefined when the text is invalid. */
export function parseOptionalInt(value: string): number | null | undefined {
  const text = value.trim();
  if (!text) return null;
  return /^\d+$/.test(text) ? Number(text) : undefined;
}

/** Share of the score bar a component fills, from 0 to 100. Unconfigured components are 0. */
export function componentFill(raw: number | null | undefined): number {
  return raw == null ? 0 : Math.round(Math.max(0, Math.min(1, raw)) * 100);
}
