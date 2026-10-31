import type { Metadata } from "next";

import { AuthCard } from "@/features/auth/auth-card";
import { UnsubscribeAction } from "@/features/outreach/unsubscribe-action";

export const metadata: Metadata = { title: "Unsubscribe", robots: { index: false } };

export default async function UnsubscribePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return (
    <AuthCard title="Stop these emails">
      <UnsubscribeAction token={token} />
    </AuthCard>
  );
}
