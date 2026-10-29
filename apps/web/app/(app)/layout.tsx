import { AppShell } from "@/components/shell/app-shell";
import { requireOrg } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  const { me, org } = await requireOrg();
  return (
    <AppShell
      user={{ email: me.user.email, name: me.user.display_name }}
      orgs={me.memberships.map((m) => ({ id: m.organization_id, name: m.organization_name }))}
      currentOrgId={org.organization_id}
    >
      {children}
    </AppShell>
  );
}
