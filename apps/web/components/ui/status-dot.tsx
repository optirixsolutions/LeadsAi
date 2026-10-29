import { clsx } from "clsx";

export type Health = "ok" | "degraded" | "down";

const STYLES: Record<Health, { dot: string; label: string }> = {
  ok: { dot: "bg-success", label: "Operational" },
  degraded: { dot: "bg-warning", label: "Degraded" },
  down: { dot: "bg-danger", label: "Unavailable" },
};

export function StatusBadge({ health, label }: { health: Health; label?: string }) {
  const s = STYLES[health];
  return (
    <span className="inline-flex items-center gap-2 text-xs text-fg-muted">
      <span className={clsx("size-2 rounded-full", s.dot)} aria-hidden />
      {label ?? s.label}
    </span>
  );
}
