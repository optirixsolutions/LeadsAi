import type { components } from "@salesiq/contracts";
import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { AuthCard } from "@/features/auth/auth-card";
import { AcceptInvitationAction } from "@/features/auth/token-actions";
import { API_URL } from "@/lib/api";
import { ROLE_LABELS, type Role } from "@/lib/roles";
import { optionalMe } from "@/lib/session";

export const metadata: Metadata = { title: "Invitation" };

type Preview = components["schemas"]["InvitationPreviewOut"];

async function preview(token: string): Promise<Preview | null> {
  const res = await fetch(`${API_URL}/api/v1/invitations/preview`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ token }),
    cache: "no-store",
  }).catch(() => null);
  return res?.ok ? ((await res.json()) as Preview) : null;
}

export default async function InvitePage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  const invitation = token ? await preview(token) : null;
  if (!token || !invitation) {
    return (
      <AuthCard title="Invitation unavailable">
        <Alert tone="error">
          This invitation is invalid, expired, or already used. Ask the sender for a new one.
        </Alert>
      </AuthCard>
    );
  }

  const me = await optionalMe();
  const back = encodeURIComponent(`/invite?token=${token}`);
  const role = ROLE_LABELS[invitation.role as Role] ?? invitation.role;

  return (
    <AuthCard
      title={`Join ${invitation.organization_name}`}
      description={`You've been invited as ${role}.`}
    >
      {!me ? (
        <div className="space-y-3 text-sm">
          <p className="text-fg-muted">
            Sign in or create an account with <strong className="text-fg">{invitation.email}</strong>{" "}
            to accept.
          </p>
          <div className="grid grid-cols-2 gap-2">
            <Link
              href={`/login?next=${back}`}
              className="inline-flex h-9 items-center justify-center rounded-md border border-border text-sm hover:bg-surface-raised"
            >
              Sign in
            </Link>
            <Link
              href={`/register?next=${back}`}
              className="inline-flex h-9 items-center justify-center rounded-md bg-accent text-sm font-medium text-accent-fg hover:bg-accent-strong"
            >
              Create account
            </Link>
          </div>
        </div>
      ) : me.user.email !== invitation.email ? (
        <Alert tone="error">
          This invitation was sent to {invitation.email}, but you are signed in as {me.user.email}.
          Sign out and use the invited address.
        </Alert>
      ) : (
        <AcceptInvitationAction token={token} orgName={invitation.organization_name} />
      )}
    </AuthCard>
  );
}
