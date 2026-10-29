"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import type { z } from "zod";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";

import { forgotSchema, resetSchema } from "./schemas";

export function ForgotPasswordForm() {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof forgotSchema>>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { email: "" },
  });

  async function onSubmit(values: z.infer<typeof forgotSchema>) {
    setError(null);
    const r = await apiRequest("/auth/password-reset/request", { method: "POST", body: values });
    if (!r.ok) setError(r.message);
    else setSent(true);
  }

  if (sent) {
    // Same message whether or not the account exists.
    return (
      <Alert tone="success">
        If an account exists for that address, a reset link is on its way. It expires in 30
        minutes.
      </Alert>
    );
  }
  const { errors, isSubmitting } = form.formState;
  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <TextField
        label="Email"
        type="email"
        autoComplete="email"
        error={errors.email?.message}
        {...form.register("email")}
      />
      <Button type="submit" loading={isSubmitting} className="w-full">
        Send reset link
      </Button>
    </form>
  );
}

export function ResetPasswordForm({ token }: { token: string }) {
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof resetSchema>>({
    resolver: zodResolver(resetSchema),
    defaultValues: { new_password: "", confirm: "" },
  });

  async function onSubmit(values: z.infer<typeof resetSchema>) {
    setError(null);
    const r = await apiRequest("/auth/password-reset/confirm", {
      method: "POST",
      body: { token, new_password: values.new_password },
    });
    if (!r.ok) setError(r.message);
    else setDone(true);
  }

  if (done) {
    return (
      <div className="space-y-4">
        <Alert tone="success">Password updated. You have been signed out everywhere.</Alert>
        <Link href="/login" className="block text-center text-sm text-accent hover:underline">
          Sign in
        </Link>
      </div>
    );
  }
  const { errors, isSubmitting } = form.formState;
  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <TextField
        label="New password"
        type="password"
        autoComplete="new-password"
        error={errors.new_password?.message}
        {...form.register("new_password")}
      />
      <TextField
        label="Confirm new password"
        type="password"
        autoComplete="new-password"
        error={errors.confirm?.message}
        {...form.register("confirm")}
      />
      <Button type="submit" loading={isSubmitting} className="w-full">
        Update password
      </Button>
    </form>
  );
}
