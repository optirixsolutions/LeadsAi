import type { Metadata } from "next";

import { Alert } from "@/components/ui/alert";
import { AuthCard } from "@/features/auth/auth-card";
import { VerifyEmailAction } from "@/features/auth/token-actions";

export const metadata: Metadata = { title: "Verify email" };

export default async function VerifyEmailPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  return (
    <AuthCard title="Verify your email">
      {token ? (
        <VerifyEmailAction token={token} />
      ) : (
        <Alert tone="error">This verification link is incomplete.</Alert>
      )}
    </AuthCard>
  );
}
