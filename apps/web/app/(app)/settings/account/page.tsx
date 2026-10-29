import type { components } from "@salesiq/contracts";
import type { Metadata } from "next";

import { Alert } from "@/components/ui/alert";
import { Card, CardHeader } from "@/components/ui/card";
import {
  ChangePasswordForm,
  ResendVerification,
  SessionList,
  SignOutButton,
} from "@/features/settings/account-panels";
import { apiGet } from "@/lib/api";
import { requireAppContext } from "@/lib/session";

export const metadata: Metadata = { title: "Account" };

type Session = components["schemas"]["SessionOut"];

export default async function AccountPage() {
  const { me } = await requireAppContext();
  const sessions = await apiGet<Session[]>("/api/v1/auth/sessions");

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Profile" action={<SignOutButton />} />
        <dl className="grid gap-4 px-5 py-4 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs text-fg-subtle">Name</dt>
            <dd className="mt-0.5">{me.user.display_name || "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-fg-subtle">Email</dt>
            <dd className="mt-0.5 flex flex-wrap items-center gap-2">
              {me.user.email}
              {me.user.email_verified ? (
                <span className="text-xs text-accent">Verified</span>
              ) : (
                <ResendVerification />
              )}
            </dd>
          </div>
        </dl>
      </Card>

      <Card>
        <CardHeader
          title="Password"
          description="Changing it signs you out of every other device."
        />
        <div className="px-5 py-4">
          <ChangePasswordForm />
        </div>
      </Card>

      {sessions.ok ? (
        <SessionList sessions={sessions.data} />
      ) : (
        <Alert tone="error">Could not load sessions: {sessions.message}</Alert>
      )}
    </div>
  );
}
