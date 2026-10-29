"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import type { z } from "zod";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";

import { MIN_PASSWORD, registerSchema, safeNext } from "./schemas";

export function RegisterForm({ next }: { next?: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof registerSchema>>({
    resolver: zodResolver(registerSchema),
    defaultValues: { display_name: "", email: "", password: "" },
  });

  async function onSubmit(values: z.infer<typeof registerSchema>) {
    setError(null);
    const r = await apiRequest("/auth/register", { method: "POST", body: values });
    if (!r.ok) {
      setError(r.message);
      return;
    }
    // Invite links carry their own destination; otherwise new users create an org first.
    router.replace(next ? safeNext(next) : "/onboarding");
    router.refresh();
  }

  const { errors, isSubmitting } = form.formState;
  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <TextField
        label="Your name"
        autoComplete="name"
        error={errors.display_name?.message}
        {...form.register("display_name")}
      />
      <TextField
        label="Work email"
        type="email"
        autoComplete="email"
        error={errors.email?.message}
        {...form.register("email")}
      />
      <TextField
        label="Password"
        type="password"
        autoComplete="new-password"
        hint={`At least ${MIN_PASSWORD} characters. A short phrase works well.`}
        error={errors.password?.message}
        {...form.register("password")}
      />
      <Button type="submit" loading={isSubmitting} className="w-full">
        Create account
      </Button>
    </form>
  );
}
