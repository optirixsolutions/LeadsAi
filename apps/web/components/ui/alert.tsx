import { clsx } from "clsx";

const TONES = {
  error: "border-danger/40 bg-danger/10 text-danger",
  success: "border-accent/40 bg-accent/10 text-accent",
  warning: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  info: "border-border bg-surface-raised text-fg-muted",
} as const;

export function Alert({
  tone,
  children,
  className,
}: {
  tone: keyof typeof TONES;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={clsx("rounded-md border px-3 py-2 text-sm", TONES[tone], className)}
    >
      {children}
    </div>
  );
}
