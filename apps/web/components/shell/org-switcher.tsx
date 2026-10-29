"use client";

import { ChevronsUpDown } from "lucide-react";
import { useRouter } from "next/navigation";

import { rememberOrg } from "@/lib/org-cookie";

export interface OrgOption {
  id: string;
  name: string;
}

const NEW_ORG = "__new__";

export function OrgSwitcher({ orgs, currentId }: { orgs: OrgOption[]; currentId: string }) {
  const router = useRouter();

  function onChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const value = e.target.value;
    if (value === NEW_ORG) {
      router.push("/onboarding");
      return;
    }
    // A preference only; the server re-validates membership on every request.
    rememberOrg(value);
    router.refresh();
  }

  return (
    <div className="relative">
      <label htmlFor="org-switcher" className="sr-only">
        Organization
      </label>
      <select
        id="org-switcher"
        value={currentId}
        onChange={onChange}
        className="h-9 w-full appearance-none truncate rounded-md border border-border bg-canvas pl-3 pr-8 text-sm hover:border-border-strong focus:border-accent focus:outline-none"
      >
        {orgs.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
        <option value={NEW_ORG}>+ New organization</option>
      </select>
      <ChevronsUpDown
        className="pointer-events-none absolute top-1/2 right-2.5 size-3.5 -translate-y-1/2 text-fg-subtle"
        aria-hidden
      />
    </div>
  );
}
