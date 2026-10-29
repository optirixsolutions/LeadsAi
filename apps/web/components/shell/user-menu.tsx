"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiRequest } from "@/lib/client-api";

export function UserMenu({
  email,
  name,
  collapsed,
}: {
  email: string;
  name: string;
  collapsed: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    await apiRequest("/auth/logout", { method: "POST" });
    router.replace("/login");
    router.refresh();
  }

  const initial = (name || email).charAt(0).toUpperCase();
  return (
    <div className="flex items-center gap-2 border-t border-border p-2">
      <span
        aria-hidden
        className="grid size-8 shrink-0 place-items-center rounded-full bg-surface-raised text-xs font-medium"
      >
        {initial}
      </span>
      {!collapsed && (
        <div className="min-w-0 flex-1">
          {name && <p className="truncate text-sm">{name}</p>}
          <p className="truncate text-xs text-fg-subtle">{email}</p>
        </div>
      )}
      <button
        type="button"
        onClick={signOut}
        disabled={busy}
        className="grid size-8 shrink-0 place-items-center rounded-md text-fg-muted hover:bg-surface-raised hover:text-fg disabled:opacity-60"
        aria-label="Sign out"
        title="Sign out"
      >
        <LogOut className="size-4" aria-hidden />
      </button>
    </div>
  );
}
