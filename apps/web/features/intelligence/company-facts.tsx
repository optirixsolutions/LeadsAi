"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { TextField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import { parseOptionalInt, type CompanyDetail } from "@/lib/intelligence";

export function CompanyFacts({
  orgId,
  company,
  canEdit,
}: {
  orgId: string;
  company: CompanyDetail;
  canEdit: boolean;
}) {
  const router = useRouter();
  const [domain, setDomain] = useState(company.domain ?? "");
  const [industry, setIndustry] = useState(company.industry ?? "");
  const [employees, setEmployees] = useState(company.employee_count?.toString() ?? "");
  const [country, setCountry] = useState(company.country ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaved(false);
    const count = parseOptionalInt(employees);
    if (count === undefined) return setError("Employee count must be a whole number.");
    setBusy(true);
    const r = await apiRequest<CompanyDetail>(`/organizations/${orgId}/companies/${company.id}`, {
      method: "PATCH",
      body: {
        domain: domain.trim() || null,
        industry: industry.trim() || null,
        employee_count: count,
        country: country.trim() || null,
      },
    });
    setBusy(false);
    if (!r.ok) return setError(r.message);
    setSaved(true);
    router.refresh();
  };

  return (
    <Card>
      <CardHeader title="Company facts" description={`${company.name}. Used for ICP fit.`} />
      {canEdit ? (
        <form onSubmit={submit} className="space-y-3 px-5 py-4" noValidate>
          {error && <Alert tone="error">{error}</Alert>}
          {saved && <Alert tone="success">Company facts saved. Reassess to use them.</Alert>}
          <TextField label="Website domain" placeholder="example.com" value={domain} onChange={(e) => setDomain(e.target.value)} />
          <TextField label="Industry" value={industry} onChange={(e) => setIndustry(e.target.value)} />
          <TextField label="Employees" inputMode="numeric" value={employees} onChange={(e) => setEmployees(e.target.value)} />
          <TextField label="Country" value={country} onChange={(e) => setCountry(e.target.value)} />
          <Button type="submit" variant="secondary" size="sm" loading={busy}>
            Save facts
          </Button>
        </form>
      ) : (
        <dl className="space-y-3 px-5 py-4 text-sm">
          {(
            [
              ["Website domain", company.domain],
              ["Industry", company.industry],
              ["Employees", company.employee_count],
              ["Country", company.country],
            ] as const
          ).map(([label, value]) => (
            <div key={label}>
              <dt className="text-xs text-fg-subtle">{label}</dt>
              <dd>{value ?? "—"}</dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  );
}
