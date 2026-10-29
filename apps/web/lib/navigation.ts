import {
  Activity,
  BarChart3,
  Bot,
  Inbox,
  KanbanSquare,
  LayoutDashboard,
  Plug,
  Settings,
  Users,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Roadmap phase that delivers the page. Items without a phase are live. */
  phase?: number;
}

export const NAV_ITEMS: NavItem[] = [
  { label: "Overview", href: "/", icon: LayoutDashboard },
  { label: "Leads", href: "/leads", icon: Users, phase: 3 },
  { label: "Pipeline", href: "/pipeline", icon: KanbanSquare, phase: 3 },
  { label: "Outreach", href: "/outreach", icon: Inbox, phase: 8 },
  { label: "Agents", href: "/agents", icon: Bot, phase: 6 },
  { label: "Analytics", href: "/analytics", icon: BarChart3, phase: 9 },
  { label: "Integrations", href: "/integrations", icon: Plug, phase: 10 },
  { label: "System status", href: "/status", icon: Activity },
  { label: "Settings", href: "/settings", icon: Settings, phase: 2 },
];

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
