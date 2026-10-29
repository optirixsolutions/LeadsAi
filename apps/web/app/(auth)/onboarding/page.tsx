import type { Metadata } from "next";
import Link from "next/link";

import { AuthCard } from "@/features/auth/auth-card";
import { CreateOrgForm } from "@/features/orgs/create-org-form";
import { requireAppContext } from "@/lib/session";

export const metadata: Metadata = { title: "Create organization" };
export const dynamic = "force-dynamic";

export default async function OnboardingPage() {
  const { me } = await requireAppContext();
  const first = me.memberships.length === 0;

  return (
    <AuthCard
      title={first ? "Set up your organization" : "Create another organization"}
      description="Your organization holds your team, leads, and settings. You'll be its owner."
      footer={
        !first && (
          <Link href="/" className="text-accent hover:underline">
            Back to SalesIQ
          </Link>
        )
      }
    >
      <CreateOrgForm />
      {first && (
        <p className="mt-4 text-xs text-fg-subtle">
          Joining an existing team? Ask an admin to invite {me.user.email}.
        </p>
      )}
    </AuthCard>
  );
}
