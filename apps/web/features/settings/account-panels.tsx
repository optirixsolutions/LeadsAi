"use client";

import type { components } from "@salesiq/contracts";
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import type { z } from "zod";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { TextField } from "@/components/ui/field";
import { changePasswordSchema } from "@/features/auth/schemas";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/format";

type Session = components["schemas"]["SessionOut"];

export function SignOutButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="secondary"
      size="sm"
      loading={busy}
      onClick={async () => {
        setBusy(true);
        await apiRequest("/auth/logout", { method: "POST" });
        router.replace("/login");
        router.refresh();
      }}
    >
      Sign out
    </Button>
  );
}

export function ResendVerification() {
  const [state, setState] = useState<"idle" | "busy" | "sent" | "error">("idle");
  if (state === "sent") return <span className="text-xs text-fg-muted">Verification email sent</span>;
  return (
    <span className="inline-flex items-center gap-2">
      <span className="text-xs text-warning">Unverified</span>
      <Button
        variant="ghost"
        size="sm"
        loading={state === "busy"}
        onClick={async () => {
          setState("busy");
          const r = await apiRequest("/auth/verify-email/resend", { method: "POST" });
          setState(r.ok ? "sent" : "error");
        }}
      >
        {state === "error" ? "Retry sending" : "Resend email"}
      </Button>
    </span>
  );
}

export function ChangePasswordForm() {
  const [result, setResult] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const form = useForm<z.infer<typeof changePasswordSchema>>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { current_password: "", new_password: "", confirm: "" },
  });

  async function onSubmit(values: z.infer<typeof changePasswordSchema>) {
    const r = await apiRequest("/auth/password", {
      method: "POST",
      body: { current_password: values.current_password, new_password: values.new_password },
    });
    if (r.ok) {
      form.reset();
      setResult({ tone: "success", text: "Password changed. Other sessions were signed out." });
    } else {
      setResult({ tone: "error", text: r.message });
    }
  }

  const { errors, isSubmitting } = form.formState;
  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="max-w-sm space-y-3">
      {result && <Alert tone={result.tone}>{result.text}</Alert>}
      <TextField
        label="Current password"
        type="password"
        autoComplete="current-password"
        error={errors.current_password?.message}
        {...form.register("current_password")}
      />
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
      <Button type="submit" loading={isSubmitting}>
        Change password
      </Button>
    </form>
  );
}

export function SessionList({ sessions }: { sessions: Session[] }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  return (
    <Card>
      <CardHeader title="Active sessions" description="Devices currently signed in to your account" />
      {error && (
        <div className="px-5 pt-3">
          <Alert tone="error">{error}</Alert>
        </div>
      )}
      <ul className="divide-y divide-border">
        {sessions.map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-4 px-5 py-3 text-sm">
            <div className="min-w-0">
              <p className="truncate">
                {s.user_agent ?? "Unknown device"}
                {s.current && <span className="ml-2 text-xs text-accent">This device</span>}
              </p>
              <p className="text-xs text-fg-subtle">
                {s.ip_address ?? "Unknown IP"} · last active {formatDateTime(s.last_seen_at)}
              </p>
            </div>
            {!s.current && (
              <ConfirmButton
                label="Revoke"
                confirmLabel="Sign out device"
                ariaLabel="Revoke session"
                onConfirm={async () => {
                  const r = await apiRequest(`/auth/sessions/${s.id}`, { method: "DELETE" });
                  setError(r.ok ? null : r.message);
                  router.refresh();
                }}
              />
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
