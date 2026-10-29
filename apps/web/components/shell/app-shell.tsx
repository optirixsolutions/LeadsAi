"use client";

import { clsx } from "clsx";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";

import { NAV_ITEMS, isActive } from "@/lib/navigation";

// UI preference only; session data never goes in localStorage.
const COLLAPSE_KEY = "salesiq.sidebar.collapsed";
const listeners = new Set<() => void>();
// In-memory fallback for when storage is unavailable (private mode, blocked site data).
let memoryCollapsed = false;

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return memoryCollapsed;
  }
}

function writeCollapsed(value: boolean) {
  memoryCollapsed = value;
  try {
    localStorage.setItem(COLLAPSE_KEY, value ? "1" : "0");
  } catch {
    /* storage unavailable; memory fallback holds the value */
  }
  listeners.forEach((l) => l());
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const collapsed = useSyncExternalStore(subscribe, readCollapsed, () => false);

  function toggle() {
    writeCollapsed(!collapsed);
  }

  const current = NAV_ITEMS.find((i) => isActive(pathname, i.href));

  return (
    <div className="flex min-h-dvh">
      <aside
        className={clsx(
          "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-border bg-surface transition-[width] duration-200 md:flex",
          collapsed ? "w-16" : "w-60",
        )}
        aria-label="Sidebar"
      >
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <span
            aria-hidden
            className="grid size-7 shrink-0 place-items-center rounded-md bg-accent font-mono text-xs font-bold text-accent-fg"
          >
            IQ
          </span>
          {!collapsed && <span className="font-semibold tracking-tight">SalesIQ</span>}
        </div>

        <nav aria-label="Primary" className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = isActive(pathname, item.href);
            const base =
              "flex h-9 items-center gap-3 rounded-md px-3 text-sm transition-colors";
            if (item.phase !== undefined) {
              // Not yet built: rendered as plain text, not a link, so nothing is clickable that does nothing.
              return (
                <div
                  key={item.href}
                  className={clsx(base, "cursor-default text-fg-subtle")}
                  title={`${item.label} ships in roadmap phase ${item.phase}`}
                  aria-disabled="true"
                >
                  <Icon className="size-4 shrink-0" aria-hidden />
                  {!collapsed && (
                    <>
                      <span className="flex-1">{item.label}</span>
                      <span className="rounded border border-border px-1.5 font-mono text-[10px]">
                        P{item.phase}
                      </span>
                    </>
                  )}
                </div>
              );
            }
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={clsx(
                  base,
                  active
                    ? "bg-surface-raised text-fg"
                    : "text-fg-muted hover:bg-surface-raised hover:text-fg",
                )}
              >
                <Icon className={clsx("size-4 shrink-0", active && "text-accent")} aria-hidden />
                {!collapsed && <span>{item.label}</span>}
              </Link>
            );
          })}
        </nav>

        <button
          type="button"
          onClick={toggle}
          className="m-2 flex h-9 items-center gap-3 rounded-md px-3 text-sm text-fg-muted hover:bg-surface-raised hover:text-fg"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <PanelLeftOpen className="size-4" aria-hidden />
          ) : (
            <>
              <PanelLeftClose className="size-4" aria-hidden />
              <span>Collapse</span>
            </>
          )}
        </button>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b border-border bg-canvas/90 px-4 backdrop-blur md:px-6">
          <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
            <ol className="flex items-center gap-2">
              <li className="md:hidden font-semibold text-fg">SalesIQ</li>
              <li className="md:hidden" aria-hidden>
                /
              </li>
              <li className="text-fg">{current?.label ?? "Page"}</li>
            </ol>
          </nav>
        </header>

        {/* Mobile navigation: live pages only */}
        <nav
          aria-label="Mobile"
          className="flex gap-1 overflow-x-auto border-b border-border px-2 py-2 md:hidden"
        >
          {NAV_ITEMS.filter((i) => i.phase === undefined).map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive(pathname, item.href) ? "page" : undefined}
              className={clsx(
                "shrink-0 rounded-md px-3 py-1.5 text-sm",
                isActive(pathname, item.href) ? "bg-surface-raised text-fg" : "text-fg-muted",
              )}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-6 md:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
