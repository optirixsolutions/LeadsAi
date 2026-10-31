import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { DraftView } from "@/features/outreach/draft-view";
import { orgGet } from "@/lib/org-api";
import type { DraftDetail } from "@/lib/outreach";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Outreach draft" };

export default async function DraftPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { org } = await requireOrg();
  const draft = await orgGet<DraftDetail>(org.organization_id, `/outreach/drafts/${encodeURIComponent(id)}`);
  if (!draft.ok) {
    if (draft.status === 404 || draft.status === 422) notFound();
    return <Alert tone="error">Could not load this draft: {draft.message}</Alert>;
  }
  const can = (p: string) => hasPermission(org.permissions, p);
  return (
    <>
      <Link href="/outreach" className="mb-4 inline-block text-sm text-accent hover:underline">
        ← Drafts
      </Link>
      <DraftView
        key={draft.data.version + draft.data.status}
        orgId={org.organization_id}
        draft={draft.data}
        canWrite={can("outreach:write")}
        canSend={can("outreach:send")}
        canApprove={can("outreach:approve")}
      />
    </>
  );
}
