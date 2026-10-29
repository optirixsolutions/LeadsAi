import { PageHeader } from "@/components/ui/page-header";
import { SettingsTabs } from "@/features/settings/settings-tabs";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader title="Settings" description="Manage your organization, team, and account." />
      <SettingsTabs />
      <div className="mt-6">{children}</div>
    </>
  );
}
