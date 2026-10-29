import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { AuthCard } from "@/features/auth/auth-card";
import { ResetPasswordForm } from "@/features/auth/password-forms";

export const metadata: Metadata = { title: "Choose a new password" };

export default async function ResetPasswordPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  return (
    <AuthCard title="Choose a new password">
      {token ? (
        <ResetPasswordForm token={token} />
      ) : (
        <Alert tone="error">
          This link is incomplete.{" "}
          <Link href="/forgot-password" className="underline">
            Request a new one
          </Link>
          .
        </Alert>
      )}
    </AuthCard>
  );
}
