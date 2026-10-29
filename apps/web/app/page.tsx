import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { HealthPanel } from "@/features/system/health-panel";

export const dynamic = "force-dynamic";

export default function OverviewPage() {
  return (
    <>
      <PageHeader
        title="Overview"
        description="Pipeline, qualification, and agent activity for your organization."
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Revenue overview"
            description="Computed from stored leads, opportunities, and verified outcomes"
          />
          {/* Metrics render only from real aggregates; none exist until lead management ships. */}
          <EmptyState
            title="No pipeline data yet"
            body="Lead and opportunity tracking arrives in roadmap phase 3. Metrics will appear here once records exist."
          />
        </Card>
        <HealthPanel />
      </div>
    </>
  );
}
