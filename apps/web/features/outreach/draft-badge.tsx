import { clsx } from "clsx";

import { DRAFT_STATUS_LABELS, DRAFT_STATUS_TONES } from "@/lib/outreach";

export function DraftBadge({ status }: { status: string }) {
  return (
    <span
      className={clsx(
        "inline-flex h-5 items-center whitespace-nowrap rounded border px-1.5 text-[11px] font-medium",
        DRAFT_STATUS_TONES[status] ?? DRAFT_STATUS_TONES.draft,
      )}
    >
      {DRAFT_STATUS_LABELS[status] ?? status}
    </span>
  );
}
