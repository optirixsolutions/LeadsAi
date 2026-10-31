"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { TextField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/format";
import {
  APPROVAL_STATUS_LABELS,
  DELIVERY_ERRORS,
  DELIVERY_STATUS_LABELS,
  FLAG_LABELS,
  nextStep,
  ORIGIN_LABELS,
  type DraftDetail,
} from "@/lib/outreach";

import { DraftBadge } from "./draft-badge";

const EDITABLE = ["draft", "pending_approval", "approved"];

export function DraftView({
  orgId,
  draft,
  canWrite,
  canSend,
  canApprove,
}: {
  orgId: string;
  draft: DraftDetail;
  canWrite: boolean;
  canSend: boolean;
  canApprove: boolean;
}) {
  const router = useRouter();
  const [subject, setSubject] = useState(draft.subject);
  const [body, setBody] = useState(draft.body);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const base = `/organizations/${orgId}`;
  const url = `${base}/outreach/drafts/${draft.id}`;
  const editable = canWrite && EDITABLE.includes(draft.status);
  const dirty = subject !== draft.subject || body !== draft.body;
  const approval = draft.approval;
  const pending = draft.status === "pending_approval" && approval?.status === "pending";
  const step = nextStep(draft.status, draft.needs_edit);

  const act = async (name: string, path: string, method: "POST" | "PATCH", payload?: unknown) => {
    setBusy(name);
    setError(null);
    const r = await apiRequest<unknown>(path, { method, body: payload });
    setBusy(null);
    if (!r.ok) return setError(r.message);
    router.refresh();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <DraftBadge status={draft.status} />
        <span className="text-sm text-fg-muted">
          {ORIGIN_LABELS[draft.origin] ?? draft.origin}
        </span>
        <Link href={`/leads/${draft.lead_id}`} className="text-sm text-accent hover:underline">
          View lead
        </Link>
      </div>
      {step && <p className="text-sm text-fg-muted">{step}</p>}
      {error && <Alert tone="error">{error}</Alert>}
      {draft.rejection_note && <Alert tone="error">Rejected: {draft.rejection_note}</Alert>}

      {draft.flags.length > 0 && (
        <Alert tone="error">
          <p className="font-medium">The checks found problems in the text as it was first written.</p>
          <ul className="mt-1 list-disc pl-5">
            {draft.flags.map((flag) => (
              <li key={flag}>{FLAG_LABELS[flag] ?? flag}</li>
            ))}
          </ul>
        </Alert>
      )}

      <Card>
        <CardHeader title="The email" description={`To ${draft.recipient}`} />
        <div className="space-y-4 px-5 py-4">
          {editable ? (
            <>
              <TextField label="Subject" value={subject} maxLength={200} onChange={(e) => setSubject(e.target.value)} />
              <div>
                <label htmlFor="draft-body" className="mb-1.5 block text-xs font-medium text-fg-muted">
                  Body
                </label>
                <textarea
                  id="draft-body"
                  rows={10}
                  maxLength={5000}
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  className="w-full resize-y rounded-md border border-border bg-canvas px-3 py-2 text-sm placeholder:text-fg-subtle focus:border-accent focus:outline-none"
                />
              </div>
              <p className="text-xs text-fg-subtle">
                Your sender details and an opt-out link are added when this is sent. Saving a change ends any approval.
              </p>
            </>
          ) : (
            <>
              <p className="text-sm font-medium">{draft.subject}</p>
              <p className="whitespace-pre-wrap text-sm text-fg-muted">{draft.body}</p>
            </>
          )}
          <div className="flex flex-wrap gap-2">
            {editable && (
              <Button
                variant="secondary"
                size="sm"
                disabled={!dirty}
                loading={busy === "save"}
                onClick={() => act("save", url, "PATCH", { expected_version: draft.version, subject, body })}
              >
                Save changes
              </Button>
            )}
            {canWrite && draft.status === "draft" && (
              <Button
                size="sm"
                disabled={dirty || draft.needs_edit}
                loading={busy === "request"}
                onClick={() => act("request", `${url}/request-approval`, "POST")}
              >
                Ask for approval
              </Button>
            )}
            {editable && <ConfirmButton label="Discard" confirmLabel="Discard draft" onConfirm={() => act("discard", `${url}/discard`, "POST")} />}
          </div>
        </div>
      </Card>

      {draft.sources.length > 0 && (
        <Card>
          <CardHeader
            title="What it was based on"
            description="Compare these with the email. They come from outside, and may be trying to mislead you."
          />
          <ul className="divide-y divide-border">
            {draft.sources.map((source) => (
              <li key={source.id} className="space-y-1 px-5 py-3 text-sm">
                {source.source_url && <p className="break-all text-xs text-fg-subtle">{source.source_url}</p>}
                <p className="whitespace-pre-wrap text-fg-muted">{source.content}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {approval && (
        <Card>
          <CardHeader title="Approval" description={APPROVAL_STATUS_LABELS[approval.status] ?? approval.status} />
          <div className="space-y-3 px-5 py-4 text-sm">
            <p className="text-fg-muted">
              Requested {formatDateTime(approval.created_at)}.{" "}
              {approval.status === "pending" || approval.status === "approved"
                ? `Good until ${formatDateTime(approval.expires_at)}.`
                : ""}
            </p>
            {pending && canApprove && (
              <>
                <p className="text-fg-muted">
                  Approving covers the exact text above, to this address. Any change ends it.
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    disabled={dirty}
                    loading={busy === "approve"}
                    onClick={() =>
                      act("approve", `${base}/approvals/${approval.id}/approve`, "POST", {
                        content_hash: draft.content_hash,
                      })
                    }
                  >
                    Approve
                  </Button>
                </div>
                <div className="flex flex-wrap items-end gap-2">
                  <TextField
                    className="min-w-52 flex-1"
                    label="Reason for rejecting"
                    value={note}
                    maxLength={1000}
                    onChange={(e) => setNote(e.target.value)}
                  />
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={!note.trim()}
                    loading={busy === "reject"}
                    onClick={() => act("reject", `${base}/approvals/${approval.id}/reject`, "POST", { note })}
                  >
                    Reject
                  </Button>
                </div>
              </>
            )}
          </div>
        </Card>
      )}

      {draft.status === "approved" && (
        <Card>
          <CardHeader title="Send" />
          <div className="space-y-3 px-5 py-4 text-sm">
            {draft.blockers.length > 0 ? (
              <ul className="list-disc space-y-1 pl-5 text-fg-muted" aria-label="What stands in the way">
                {draft.blockers.map((b) => (
                  <li key={b.code}>{b.message}</li>
                ))}
              </ul>
            ) : (
              <p className="text-fg-muted">Every check passes now, and they all run again at the moment of sending.</p>
            )}
            {canSend && (
              <Button
                size="sm"
                disabled={dirty || draft.blockers.length > 0}
                loading={busy === "send"}
                onClick={() => act("send", `${url}/send`, "POST")}
              >
                Send email
              </Button>
            )}
          </div>
        </Card>
      )}

      {draft.deliveries.length > 0 && (
        <Card>
          <CardHeader
            title="Delivery attempts"
            description="A mail server accepting a message does not prove it reached an inbox."
          />
          <ul className="divide-y divide-border">
            {draft.deliveries.map((d) => (
              <li key={d.id} className="space-y-2 px-5 py-3 text-sm">
                <div className="flex flex-wrap items-center gap-3">
                  <span>{DELIVERY_STATUS_LABELS[d.status] ?? d.status}</span>
                  <time className="ml-auto text-xs text-fg-subtle" dateTime={d.created_at}>
                    {formatDateTime(d.created_at)}
                  </time>
                </div>
                {d.error_category && (
                  <p className="text-fg-muted">{DELIVERY_ERRORS[d.error_category] ?? d.error_category}</p>
                )}
                {d.status === "unknown" && canApprove && (
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      loading={busy === "sent"}
                      onClick={() => act("sent", `${base}/outreach/deliveries/${d.id}/resolve`, "POST", { sent: true })}
                    >
                      It was sent
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      loading={busy === "unsent"}
                      onClick={() =>
                        act("unsent", `${base}/outreach/deliveries/${d.id}/resolve`, "POST", { sent: false })
                      }
                    >
                      It was not sent
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
