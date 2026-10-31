"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { TextField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import type { OutreachSettings } from "@/lib/outreach";

export function SettingsForm({
  orgId,
  settings,
  canEdit,
}: {
  orgId: string;
  settings: OutreachSettings;
  canEdit: boolean;
}) {
  const router = useRouter();
  const [enabled, setEnabled] = useState(settings.sends_enabled);
  const [name, setName] = useState(settings.sender_name ?? "");
  const [email, setEmail] = useState(settings.sender_email ?? "");
  const [address, setAddress] = useState(settings.postal_address ?? "");
  const [timezone, setTimezone] = useState(settings.timezone);
  const [start, setStart] = useState(settings.quiet_start_hour?.toString() ?? "");
  const [end, setEnd] = useState(settings.quiet_end_hour?.toString() ?? "");
  const [limit, setLimit] = useState(settings.daily_limit.toString());
  const [recontact, setRecontact] = useState(settings.recontact_days.toString());
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setSaved(false);
    setError(null);
    const r = await apiRequest<OutreachSettings>(`/organizations/${orgId}/outreach/settings`, {
      method: "PUT",
      body: {
        sends_enabled: enabled,
        sender_name: name || null,
        sender_email: email || null,
        postal_address: address || null,
        timezone,
        quiet_start_hour: start === "" ? null : Number(start),
        quiet_end_hour: end === "" ? null : Number(end),
        daily_limit: Number(limit),
        recontact_days: Number(recontact),
      },
    });
    setBusy(false);
    if (!r.ok) return setError(r.message);
    setSaved(true);
    router.refresh();
  };

  return (
    <Card>
      <CardHeader title="Sending" description="With sending off, approved drafts wait. They are not lost." />
      <form onSubmit={save} className="space-y-5 px-5 py-4" noValidate>
        {settings.server_blocker && <Alert tone="error">{settings.server_blocker.message}</Alert>}
        {error && <Alert tone="error">{error}</Alert>}
        {saved && <Alert tone="success">Settings saved.</Alert>}
        <fieldset disabled={!canEdit} className="space-y-5">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Allow this organization to send approved email
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField label="Sender name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
            <TextField label="Sender email" type="email" value={email} maxLength={320} onChange={(e) => setEmail(e.target.value)} />
            <TextField
              className="sm:col-span-2"
              label="Postal address"
              hint="Commercial email has to carry one in many countries. It is added to every message."
              value={address}
              maxLength={300}
              onChange={(e) => setAddress(e.target.value)}
            />
            <TextField label="Time zone" hint="For example Asia/Karachi." value={timezone} maxLength={64} onChange={(e) => setTimezone(e.target.value)} />
            <div className="grid grid-cols-2 gap-4">
              <TextField label="Quiet from (hour)" type="number" min={0} max={23} value={start} onChange={(e) => setStart(e.target.value)} />
              <TextField label="Quiet until (hour)" type="number" min={0} max={23} value={end} onChange={(e) => setEnd(e.target.value)} />
            </div>
            <TextField label="Most emails per day" type="number" min={1} max={10000} value={limit} onChange={(e) => setLimit(e.target.value)} />
            <TextField
              label="Days before contacting an address again"
              type="number"
              min={0}
              max={365}
              value={recontact}
              onChange={(e) => setRecontact(e.target.value)}
            />
          </div>
          {canEdit && (
            <Button type="submit" size="sm" loading={busy}>
              Save settings
            </Button>
          )}
        </fieldset>
      </form>
    </Card>
  );
}
