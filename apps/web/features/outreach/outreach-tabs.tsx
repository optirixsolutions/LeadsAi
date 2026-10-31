"use client";

import { clsx } from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/outreach", label: "Drafts" },
  { href: "/outreach/approvals", label: "Approvals" },
  { href: "/outreach/suppressions", label: "Suppression list" },
  { href: "/outreach/settings", label: "Settings" },
];

export function OutreachTabs() {
  const pathname = usePathname();
  return (
    <nav aria-label="Outreach" className="flex gap-1 overflow-x-auto border-b border-border">
      {TABS.map((t) => {
        const active = pathname === t.href;
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active ? "page" : undefined}
            className={clsx(
              "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors",
              active ? "border-accent text-fg" : "border-transparent text-fg-muted hover:text-fg",
            )}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
