"use client";

import type { components } from "@salesiq/contracts";
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { SelectField, TextField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import { formatDate as formatDateValue } from "@/lib/format";
import { assignableRoles, canManage, ROLE_LABELS, type Role } from "@/lib/roles";

type Member = components["schemas"]["MemberOut"];
type Invitation = components["schemas"]["InvitationOut"];

const inviteSchema = z.object({
  email: z.string().trim().min(1, "Enter an email").pipe(z.email("Enter a valid email")),
  role: z.enum(["owner", "admin", "manager", "sales_rep", "analyst"]),
});

function formatDate(iso: string): string {
  return formatDateValue(iso);
}

export function TeamManager({
  orgId,
  myUserId,
  myRole,
  canInvite,
  members,
  invitations,
}: {
  orgId: string;
  myUserId: string;
  myRole: Role;
  canInvite: boolean;
  members: Member[];
  invitations: Invitation[];
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const base = `/organizations/${orgId}`;
  const grantable = assignableRoles(myRole);

  async function run(action: () => Promise<{ ok: boolean; message?: string }>, success: string) {
    setError(null);
    setNotice(null);
    const r = await action();
    if (!r.ok) setError(r.message ?? "Request failed");
    else setNotice(success);
    router.refresh();
  }

  const form = useForm<z.infer<typeof inviteSchema>>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: "", role: grantable.at(-1) ?? "analyst" },
  });

  async function invite(values: z.infer<typeof inviteSchema>) {
    await run(
      () => apiRequest(`${base}/invitations`, { method: "POST", body: values }),
      `Invitation sent to ${values.email}.`,
    );
    form.reset({ email: "", role: values.role });
  }

  return (
    <div className="space-y-6">
      {error && <Alert tone="error">{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}

      <Card>
        <CardHeader
          title="Members"
          description={`${members.length} ${members.length === 1 ? "person" : "people"} in this organization`}
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-fg-subtle">
              <tr className="border-b border-border">
                <th className="px-5 py-2 font-medium">Member</th>
                <th className="px-5 py-2 font-medium">Role</th>
                <th className="hidden px-5 py-2 font-medium sm:table-cell">Joined</th>
                <th className="px-5 py-2">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {members.map((m) => {
                const self = m.user_id === myUserId;
                const role = m.role as Role;
                const manageable = !self && canManage(myRole, role);
                return (
                  <tr key={m.id}>
                    <td className="px-5 py-3">
                      <p>{m.display_name || m.email}</p>
                      {m.display_name && <p className="text-xs text-fg-subtle">{m.email}</p>}
                    </td>
                    <td className="px-5 py-3">
                      {manageable ? (
                        <SelectField
                          label={`Role for ${m.email}`}
                          hideLabel
                          value={role}
                          className="w-44"
                          onChange={(e) =>
                            run(
                              () =>
                                apiRequest(`${base}/members/${m.id}`, {
                                  method: "PATCH",
                                  body: { role: e.target.value },
                                }),
                              `Updated ${m.email}.`,
                            )
                          }
                        >
                          {grantable.map((r) => (
                            <option key={r} value={r}>
                              {ROLE_LABELS[r]}
                            </option>
                          ))}
                        </SelectField>
                      ) : (
                        <span className="text-fg-muted">
                          {ROLE_LABELS[role]}
                          {self && " (you)"}
                        </span>
                      )}
                    </td>
                    <td className="hidden px-5 py-3 text-fg-muted sm:table-cell">
                      {formatDate(m.joined_at)}
                    </td>
                    <td className="px-5 py-3 text-right">
                      {(manageable || self) && (
                        <ConfirmButton
                          label={self ? "Leave" : "Remove"}
                          confirmLabel={self ? "Leave organization" : "Confirm removal"}
                          ariaLabel={self ? "Leave organization" : `Remove ${m.email}`}
                          onConfirm={async () => {
                            await run(
                              () => apiRequest(`${base}/members/${m.id}`, { method: "DELETE" }),
                              self ? "You left the organization." : `Removed ${m.email}.`,
                            );
                          }}
                        />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {canInvite && (
        <Card>
          <CardHeader
            title="Invite people"
            description="Invitations expire after 7 days and must be accepted by the invited address."
          />
          <form
            onSubmit={form.handleSubmit(invite)}
            noValidate
            className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-end"
          >
            <TextField
              label="Email"
              type="email"
              className="flex-1"
              error={form.formState.errors.email?.message}
              {...form.register("email")}
            />
            <SelectField label="Role" className="sm:w-48" {...form.register("role")}>
              {grantable.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r]}
                </option>
              ))}
            </SelectField>
            <Button type="submit" loading={form.formState.isSubmitting}>
              Send invite
            </Button>
          </form>

          <div className="border-t border-border">
            {invitations.length === 0 ? (
              <EmptyState title="No pending invitations" body="Invited people appear here until they accept." />
            ) : (
              <ul className="divide-y divide-border">
                {invitations.map((inv) => (
                  <li key={inv.id} className="flex items-center justify-between gap-4 px-5 py-3 text-sm">
                    <div>
                      <p>{inv.email}</p>
                      <p className="text-xs text-fg-subtle">
                        {ROLE_LABELS[inv.role as Role]} · expires {formatDate(inv.expires_at)}
                      </p>
                    </div>
                    {canManage(myRole, inv.role as Role) && (
                      <ConfirmButton
                        label="Revoke"
                        confirmLabel="Confirm revoke"
                        ariaLabel={`Revoke invitation for ${inv.email}`}
                        onConfirm={async () => {
                          await run(
                            () => apiRequest(`${base}/invitations/${inv.id}`, { method: "DELETE" }),
                            `Revoked invitation for ${inv.email}.`,
                          );
                        }}
                      />
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
