import type { components } from "@salesiq/contracts";
import type { Metadata } from "next";

import { Alert } from "@/components/ui/alert";
import { TeamManager } from "@/features/settings/team-manager";
import { apiGet } from "@/lib/api";
import { hasPermission, type Role } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Team" };

type Member = components["schemas"]["MemberOut"];
type Invitation = components["schemas"]["InvitationOut"];

export default async function TeamPage() {
  const { me, org } = await requireOrg();
  const base = `/api/v1/organizations/${org.organization_id}`;
  const canInvite = hasPermission(org.permissions, "members:invite");

  const [members, invitations] = await Promise.all([
    apiGet<Member[]>(`${base}/members`),
    canInvite ? apiGet<Invitation[]>(`${base}/invitations`) : Promise.resolve(null),
  ]);
  if (!members.ok) return <Alert tone="error">Could not load members: {members.message}</Alert>;
  if (invitations && !invitations.ok) {
    return <Alert tone="error">Could not load invitations: {invitations.message}</Alert>;
  }

  return (
    <TeamManager
      orgId={org.organization_id}
      myUserId={me.user.id}
      myRole={org.role as Role}
      canInvite={canInvite}
      members={members.data}
      invitations={invitations?.data ?? []}
    />
  );
}
