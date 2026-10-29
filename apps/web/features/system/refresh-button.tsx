"use client";

import { clsx } from "clsx";
import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

export function RefreshButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <button
      type="button"
      onClick={() => startTransition(() => router.refresh())}
      disabled={pending}
      className="inline-flex h-8 items-center gap-2 rounded-md border border-border px-3 text-xs text-fg-muted hover:border-border-strong hover:text-fg disabled:opacity-60"
    >
      <RefreshCw className={clsx("size-3.5", pending && "animate-spin")} aria-hidden />
      {pending ? "Checking…" : "Recheck"}
    </button>
  );
}
