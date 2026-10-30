"use client";

import { clsx } from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/settings/team", label: "Team" },
  { href: "/settings/organization", label: "Organization" },
  { href: "/settings/icp", label: "ICP and scoring" },
  { href: "/settings/account", label: "Account" },
];

export function SettingsTabs() {
  const pathname = usePathname();
  return (
    <nav aria-label="Settings" className="flex gap-1 border-b border-border">
      {TABS.map((t) => {
        const active = pathname === t.href;
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active ? "page" : undefined}
            className={clsx(
              "-mb-px border-b-2 px-3 py-2 text-sm transition-colors",
              active
                ? "border-accent text-fg"
                : "border-transparent text-fg-muted hover:text-fg",
            )}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
