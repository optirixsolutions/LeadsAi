import { clsx } from "clsx";

import { RUN_LABELS, RUN_TONES } from "@/lib/workflows";

export function RunBadge({ status }: { status: string }) {
  return (
    <span
      className={clsx(
        "inline-flex h-5 items-center whitespace-nowrap rounded border px-1.5 text-[11px] font-medium",
        RUN_TONES[status] ?? RUN_TONES.queued,
      )}
    >
      {RUN_LABELS[status] ?? status}
    </span>
  );
}
