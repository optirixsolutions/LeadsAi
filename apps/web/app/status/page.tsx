import type { Metadata } from "next";

import { PageHeader } from "@/components/ui/page-header";
import { HealthPanel } from "@/features/system/health-panel";

export const metadata: Metadata = { title: "System status" };
export const dynamic = "force-dynamic";

export default function StatusPage() {
  return (
    <>
      <PageHeader
        title="System status"
        description="Readiness of the API and the services it depends on."
      />
      <div className="max-w-2xl">
        <HealthPanel />
      </div>
    </>
  );
}
