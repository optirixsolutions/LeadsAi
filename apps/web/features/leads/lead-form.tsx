"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { SelectField, TextField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import { LEAD_STATUSES, STATUS_LABELS, type Lead, type Member } from "@/lib/crm";

const optional = (max: number) => z.string().trim().max(max, `At most ${max} characters`);

export const leadSchema = z
  .object({
    first_name: optional(120),
    last_name: optional(120),
    email: z.union([z.literal(""), z.string().trim().pipe(z.email("Enter a valid email"))]),
    title: optional(200),
    phone: optional(40),
    linkedin_url: z.union([
      z.literal(""),
      z.string().trim().max(400).regex(/^https?:\/\//i, "Must start with http:// or https://"),
    ]),
    company_name: optional(200),
    status: z.enum(LEAD_STATUSES),
    owner_user_id: z.string(),
    tags: z.string().max(1100),
  })
  .refine((v) => v.email || v.first_name || v.last_name, {
    path: ["email"],
    message: "Enter an email or a name",
  });

export type LeadFormValues = z.infer<typeof leadSchema>;

/** Convert form strings to the API's shape: blanks become null, tags become a list. */
export function toPayload(v: LeadFormValues) {
  const blank = (s: string) => (s.trim() ? s.trim() : null);
  return {
    first_name: blank(v.first_name),
    last_name: blank(v.last_name),
    email: blank(v.email),
    title: blank(v.title),
    phone: blank(v.phone),
    linkedin_url: blank(v.linkedin_url),
    company_name: blank(v.company_name),
    status: v.status,
    owner_user_id: v.owner_user_id || null,
    tags: v.tags.split(",").map((t) => t.trim()).filter(Boolean),
  };
}

export function LeadForm({
  orgId,
  members,
  lead,
  onSaved,
}: {
  orgId: string;
  members: Member[];
  lead?: Lead;
  onSaved?: () => void;
}) {
  const router = useRouter();
  const [error, setError] = useState<{ text: string; existingId?: string } | null>(null);
  const form = useForm<LeadFormValues>({
    resolver: zodResolver(leadSchema),
    defaultValues: {
      first_name: lead?.first_name ?? "",
      last_name: lead?.last_name ?? "",
      email: lead?.email ?? "",
      title: lead?.title ?? "",
      phone: lead?.phone ?? "",
      linkedin_url: lead?.linkedin_url ?? "",
      company_name: lead?.company?.name ?? "",
      status: (lead?.status as LeadFormValues["status"]) ?? "new",
      owner_user_id: lead?.owner_user_id ?? "",
      tags: lead?.tags.join(", ") ?? "",
    },
  });

  async function onSubmit(values: LeadFormValues) {
    setError(null);
    const payload = toPayload(values);
    // On edit, keep the company link unless the name was changed.
    const body = lead && values.company_name === (lead.company?.name ?? "")
      ? { ...payload, company_name: undefined }
      : payload;
    const r = await apiRequest<Lead>(
      lead ? `/organizations/${orgId}/leads/${lead.id}` : `/organizations/${orgId}/leads`,
      { method: lead ? "PATCH" : "POST", body },
    );
    if (!r.ok) {
      const existing = (r.details as { existing_lead_id?: string } | undefined)?.existing_lead_id;
      setError({ text: r.message, existingId: existing });
      return;
    }
    if (lead) {
      onSaved?.();
      router.refresh();
    } else {
      router.push(`/leads/${r.data.id}`);
    }
  }

  const { errors, isSubmitting } = form.formState;
  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
      {error && (
        <Alert tone="error">
          {error.text}
          {error.existingId && (
            <>
              {" "}
              <Link href={`/leads/${error.existingId}`} className="underline">
                Open the existing lead
              </Link>
            </>
          )}
        </Alert>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="First name" autoComplete="off" error={errors.first_name?.message} {...form.register("first_name")} />
        <TextField label="Last name" autoComplete="off" error={errors.last_name?.message} {...form.register("last_name")} />
        <TextField label="Email" type="email" autoComplete="off" error={errors.email?.message} {...form.register("email")} />
        <TextField label="Title" error={errors.title?.message} {...form.register("title")} />
        <TextField label="Company" error={errors.company_name?.message} {...form.register("company_name")} />
        <TextField label="Phone" type="tel" error={errors.phone?.message} {...form.register("phone")} />
        <TextField
          label="LinkedIn URL"
          type="url"
          className="sm:col-span-2"
          error={errors.linkedin_url?.message}
          {...form.register("linkedin_url")}
        />
        <SelectField label="Status" {...form.register("status")}>
          {LEAD_STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </SelectField>
        <SelectField label="Owner" {...form.register("owner_user_id")}>
          <option value="">Unassigned</option>
          {members.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.display_name || m.email}
            </option>
          ))}
        </SelectField>
        <TextField
          label="Tags"
          hint="Comma separated"
          className="sm:col-span-2"
          error={errors.tags?.message}
          {...form.register("tags")}
        />
      </div>
      <Button type="submit" loading={isSubmitting}>
        {lead ? "Save changes" : "Create lead"}
      </Button>
    </form>
  );
}

