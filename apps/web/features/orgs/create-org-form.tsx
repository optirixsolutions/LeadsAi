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
import { rememberOrg } from "@/lib/org-cookie";

export function CreateOrgForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof orgNameSchema>>({
    resolver: zodResolver(orgNameSchema),
    defaultValues: { name: "" },
  });

  async function onSubmit(values: z.infer<typeof orgNameSchema>) {
    setError(null);
    const r = await apiRequest<{ id: string }>("/organizations", { method: "POST", body: values });
    if (!r.ok) {
      setError(r.message);
      return;
    }
    rememberOrg(r.data.id);
    router.replace("/");
    router.refresh();
  }

  const { errors, isSubmitting } = form.formState;
  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <TextField
        label="Organization name"
        placeholder="Acme Inc."
        error={errors.name?.message}
        {...form.register("name")}
      />
      <Button type="submit" loading={isSubmitting} className="w-full">
        Create organization
      </Button>
    </form>
  );
}
