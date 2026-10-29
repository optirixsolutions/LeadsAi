import { clsx } from "clsx";

import { STATUS_LABELS, type LeadStatus } from "@/lib/crm";

const TONES: Record<LeadStatus, string> = {
  new: "border-border text-fg-muted",
  contacted: "border-sky-500/40 text-sky-300",
  qualified: "border-accent/50 text-accent",
  disqualified: "border-danger/40 text-danger",
};

export function LeadStatusBadge({ status }: { status: string }) {
  const s = status as LeadStatus;
  return (
    <span
      className={clsx(
        "inline-flex h-5 items-center rounded border px-1.5 text-[11px] font-medium",
        TONES[s] ?? TONES.new,
      )}
    >
      {STATUS_LABELS[s] ?? status}
    </span>
  );
}
