"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { SelectField, TextField } from "@/components/ui/field";
import { LEAD_STATUSES, STATUS_LABELS, type Member } from "@/lib/crm";

const SORTS = [
  { value: "-created_at", label: "Newest first" },
  { value: "created_at", label: "Oldest first" },
  { value: "-updated_at", label: "Recently updated" },
  { value: "last_name", label: "Last name A–Z" },
  { value: "email", label: "Email A–Z" },
];

/** Filters live in the URL so views are shareable and survive reloads. */
export function LeadFilters({ members }: { members: Member[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");

  function apply(changes: Record<string, string>) {
    const next = new URLSearchParams(params);
    next.delete("cursor"); // any filter change restarts pagination
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    router.replace(`${pathname}?${next}`);
  }

  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        apply({ q: q.trim() });
      }}
      className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end"
    >
      <TextField
        label="Search"
        type="search"
        placeholder="Name, email, company, title"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="sm:w-72"
      />
      <SelectField
        label="Status"
        value={params.get("status") ?? ""}
        onChange={(e) => apply({ status: e.target.value })}
        className="sm:w-40"
      >
        <option value="">Any status</option>
        {LEAD_STATUSES.map((s) => (
          <option key={s} value={s}>
            {STATUS_LABELS[s]}
          </option>
        ))}
      </SelectField>
      <SelectField
        label="Owner"
        value={params.get("owner") ?? ""}
        onChange={(e) => apply({ owner: e.target.value })}
        className="sm:w-44"
      >
        <option value="">Anyone</option>
        <option value="none">Unassigned</option>
        {members.map((m) => (
          <option key={m.user_id} value={m.user_id}>
            {m.display_name || m.email}
          </option>
        ))}
      </SelectField>
      <SelectField
        label="Sort"
        value={params.get("sort") ?? "-created_at"}
        onChange={(e) => apply({ sort: e.target.value === "-created_at" ? "" : e.target.value })}
        className="sm:w-44"
      >
        {SORTS.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </SelectField>
      <Button type="submit" variant="secondary">
        Search
      </Button>
    </form>
  );
}
