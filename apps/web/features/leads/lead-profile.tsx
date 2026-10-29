"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { SelectField, TextField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import { memberName, type Lead, type Member, type Stage } from "@/lib/crm";

import { LeadForm } from "./lead-form";

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-fg-subtle">{label}</dt>
      <dd className="mt-0.5 truncate">{children || "—"}</dd>
    </div>
  );
}

export function LeadDetails({
  orgId,
  lead,
  members,
  canEdit,
}: {
  orgId: string;
  lead: Lead;
  members: Member[];
  canEdit: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const custom = Object.entries(lead.custom_fields);

  return (
    <Card>
      <CardHeader
        title="Details"
        action={
          canEdit && (
            <Button variant="secondary" size="sm" onClick={() => setEditing((e) => !e)}>
              {editing ? "Cancel" : "Edit"}
            </Button>
          )
        }
      />
      <div className="px-5 py-4">
        {editing ? (
          <LeadForm orgId={orgId} members={members} lead={lead} onSaved={() => setEditing(false)} />
        ) : (
          <dl className="grid gap-4 text-sm sm:grid-cols-2">
            <Detail label="Email">
              {lead.email && (
                <a href={`mailto:${lead.email}`} className="hover:text-accent">
                  {lead.email}
                </a>
              )}
            </Detail>
            <Detail label="Phone">{lead.phone}</Detail>
            <Detail label="Company">
              {lead.company && (
                <>
                  {lead.company.name}
                  {lead.company.domain && <span className="text-fg-subtle"> · {lead.company.domain}</span>}
                </>
              )}
            </Detail>
            <Detail label="Owner">{memberName(members, lead.owner_user_id)}</Detail>
            <Detail label="LinkedIn">
              {lead.linkedin_url && (
                // Scheme validated server-side (http/https only).
                <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer nofollow" className="hover:text-accent">
                  Profile ↗
                </a>
              )}
            </Detail>
            <Detail label="Tags">{lead.tags.join(", ")}</Detail>
            {custom.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-xs text-fg-subtle">Custom fields</dt>
                <dd className="mt-1 grid gap-x-4 gap-y-1 sm:grid-cols-2">
                  {custom.map(([k, v]) => (
                    <p key={k} className="truncate">
                      <span className="text-fg-muted">{k}:</span> {String(v)}
                    </p>
                  ))}
                </dd>
              </div>
            )}
          </dl>
        )}
      </div>
    </Card>
  );
}

const noteSchema = z.object({ body: z.string().trim().min(1, "Write a note first").max(5000) });

export function NoteForm({ orgId, leadId }: { orgId: string; leadId: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof noteSchema>>({
    resolver: zodResolver(noteSchema),
    defaultValues: { body: "" },
  });

  async function onSubmit(values: z.infer<typeof noteSchema>) {
    setError(null);
    const r = await apiRequest(`/organizations/${orgId}/leads/${leadId}/notes`, { method: "POST", body: values });
    if (!r.ok) {
      setError(r.message);
      return;
    }
    form.reset();
    router.refresh();
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-2">
      {error && <Alert tone="error">{error}</Alert>}
      <label htmlFor="note-body" className="sr-only">
        Add a note
      </label>
      <textarea
        id="note-body"
        rows={2}
        placeholder="Add a note"
        aria-invalid={form.formState.errors.body ? true : undefined}
        className="w-full resize-y rounded-md border border-border bg-canvas px-3 py-2 text-sm placeholder:text-fg-subtle focus:border-accent focus:outline-none"
        {...form.register("body")}
      />
      {form.formState.errors.body && <p className="text-xs text-danger">{form.formState.errors.body.message}</p>}
      <Button type="submit" size="sm" loading={form.formState.isSubmitting}>
        Add note
      </Button>
    </form>
  );
}

const oppSchema = z.object({
  name: z.string().trim().min(1, "Name the opportunity").max(200),
  stage_id: z.string().min(1),
  amount: z.union([z.literal(""), z.string().regex(/^\d{1,12}(\.\d{1,2})?$/, "Use a number like 12500 or 99.50")]),
  currency: z.string().regex(/^[A-Z]{3}$/, "Three-letter code, e.g. USD"),
  expected_close_date: z.string(),
});

export function OpportunityForm({
  orgId,
  leadId,
  defaultName,
  stages,
}: {
  orgId: string;
  leadId: string;
  defaultName: string;
  stages: Stage[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof oppSchema>>({
    resolver: zodResolver(oppSchema),
    defaultValues: { name: defaultName, stage_id: stages[0]?.id ?? "", amount: "", currency: "USD", expected_close_date: "" },
  });

  async function onSubmit(v: z.infer<typeof oppSchema>) {
    setError(null);
    const r = await apiRequest(`/organizations/${orgId}/opportunities`, {
      method: "POST",
      body: {
        name: v.name,
        stage_id: v.stage_id,
        lead_id: leadId,
        amount: v.amount || null,
        currency: v.currency,
        expected_close_date: v.expected_close_date || null,
      },
    });
    if (!r.ok) {
      setError(r.message);
      return;
    }
    setOpen(false);
    form.reset();
    router.refresh();
  }

  if (!open) {
    return (
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        New opportunity
      </Button>
    );
  }
  const { errors, isSubmitting } = form.formState;
  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-3">
      {error && <Alert tone="error">{error}</Alert>}
      <TextField label="Opportunity name" error={errors.name?.message} {...form.register("name")} />
      <SelectField label="Stage" {...form.register("stage_id")}>
        {stages.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </SelectField>
      <div className="grid grid-cols-3 gap-2">
        <TextField label="Amount" inputMode="decimal" className="col-span-2" error={errors.amount?.message} {...form.register("amount")} />
        <TextField label="Currency" maxLength={3} error={errors.currency?.message} {...form.register("currency", { setValueAs: (v: string) => v.toUpperCase() })} />
      </div>
      <TextField label="Expected close" type="date" {...form.register("expected_close_date")} />
      <div className="flex gap-2">
        <Button type="submit" size="sm" loading={isSubmitting}>
          Create
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

export function DeleteLeadButton({ orgId, leadId }: { orgId: string; leadId: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="flex items-center gap-2">
      {error && <span className="text-xs text-danger">{error}</span>}
      <ConfirmButton
        label="Delete lead"
        confirmLabel="Confirm delete"
        onConfirm={async () => {
          const r = await apiRequest(`/organizations/${orgId}/leads/${leadId}`, { method: "DELETE" });
          if (!r.ok) {
            setError(r.message);
            return;
          }
          router.replace("/leads");
          router.refresh();
        }}
      />
    </div>
  );
}
