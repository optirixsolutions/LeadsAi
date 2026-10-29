"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import type { z } from "zod";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { orgNameSchema } from "@/features/auth/schemas";
import { apiRequest } from "@/lib/client-api";

export function OrgNameForm({ orgId, name }: { orgId: string; name: string }) {
  const router = useRouter();
  const [result, setResult] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const form = useForm<z.infer<typeof orgNameSchema>>({
    resolver: zodResolver(orgNameSchema),
    defaultValues: { name },
  });

  async function onSubmit(values: z.infer<typeof orgNameSchema>) {
    const r = await apiRequest(`/organizations/${orgId}`, { method: "PATCH", body: values });
    setResult(r.ok ? { tone: "success", text: "Saved." } : { tone: "error", text: r.message });
    if (r.ok) {
      form.reset(values);
      router.refresh();
    }
  }

  const { errors, isSubmitting, isDirty } = form.formState;
  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-3">
      {result && <Alert tone={result.tone}>{result.text}</Alert>}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <TextField
          label="Organization name"
          className="flex-1 sm:max-w-sm"
          error={errors.name?.message}
          {...form.register("name")}
        />
        <Button type="submit" loading={isSubmitting} disabled={!isDirty}>
          Save
        </Button>
      </div>
    </form>
  );
}
