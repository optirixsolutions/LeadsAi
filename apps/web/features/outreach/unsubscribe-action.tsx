"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { apiRequest } from "@/lib/client-api";

/** Needs a click, because mail scanners open links and must not unsubscribe anyone. */
export function UnsubscribeAction({ token }: { token: string }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<"done" | "invalid" | string | null>(null);

  const confirm = async () => {
    setBusy(true);
    const r = await apiRequest<{ unsubscribed: boolean }>(`/unsubscribe/${encodeURIComponent(token)}`, {
      method: "POST",
    });
    setBusy(false);
    if (!r.ok) return setResult(r.message);
    setResult(r.data.unsubscribed ? "done" : "invalid");
  };

  if (result === "done") return <Alert tone="success">You will not get these emails again.</Alert>;
  if (result === "invalid") return <Alert tone="error">This link is not valid. Reply to the email and ask to be removed.</Alert>;
  return (
    <div className="space-y-3">
      {result && <Alert tone="error">{result}</Alert>}
      <Button onClick={confirm} loading={busy} className="w-full">
        Unsubscribe
      </Button>
    </div>
  );
}
