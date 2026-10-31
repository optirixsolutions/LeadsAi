import { PageHeader } from "@/components/ui/page-header";
import { OutreachTabs } from "@/features/outreach/outreach-tabs";

export default function OutreachLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader title="Outreach" description="Drafts, who has to approve them, and who must not be contacted." />
      <OutreachTabs />
      <div className="mt-6">{children}</div>
    </>
  );
}
