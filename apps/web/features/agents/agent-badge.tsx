import { clsx } from "clsx";

import { AGENT_STATUS_LABELS, AGENT_STATUS_TONES } from "@/lib/agents";

export function AgentBadge({ status }: { status: string }) {
  return (
    <span
      className={clsx(
        "inline-flex h-5 items-center whitespace-nowrap rounded border px-1.5 text-[11px] font-medium",
        AGENT_STATUS_TONES[status] ?? AGENT_STATUS_TONES.running,
      )}
    >
      {AGENT_STATUS_LABELS[status] ?? status}
    </span>
  );
}
