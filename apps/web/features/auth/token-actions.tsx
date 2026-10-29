"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { apiRequest } from "@/lib/client-api";
import { rememberOrg } from "@/lib/org-cookie";

/**
 * Email links open a page with a button rather than acting on load, so link scanners
 * that prefetch URLs cannot consume single-use tokens.
 */
export function VerifyEmailAction({ token }: { token: string }) {
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setState("busy");
    setError(null);
    const r = await apiRequest("/auth/verify-email", { method: "POST", body: { token } });
    if (r.ok) setState("done");
    else {
      setError(r.message);
      setState("idle");
    }
  }

  if (state === "done") {
    return (
      <div className="space-y-4">
        <Alert tone="success">Email verified.</Alert>
        <Link href="/" className="block text-center text-sm text-accent hover:underline">
          Continue to SalesIQ
        </Link>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <Button onClick={confirm} loading={state === "busy"} className="w-full">
        Confirm my email
      </Button>
    </div>
  );
}

export function AcceptInvitationAction({ token, orgName }: { token: string; orgName: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function accept() {
    setBusy(true);
    setError(null);
    const r = await apiRequest<{ id: string }>("/invitations/accept", {
      method: "POST",
      body: { token },
    });
    if (!r.ok) {
      setError(r.message);
      setBusy(false);
      return;
    }
    rememberOrg(r.data.id);
    router.replace("/");
    router.refresh();
  }

  return (
    <div className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <Button onClick={accept} loading={busy} className="w-full">
        Join {orgName}
      </Button>
    </div>
  );
}
