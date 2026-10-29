"use client";

import type { components } from "@salesiq/contracts";
import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { SelectField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import { formatNumber } from "@/lib/format";

type Preview = components["schemas"]["ImportPreviewOut"];
type ImportResult = components["schemas"]["ImportOut"];
type LeadField = NonNullable<Preview["suggested_mapping"][string]>;

const MAX_BYTES = 5 * 1024 * 1024;

const FIELD_LABELS: Record<LeadField, string> = {
  email: "Email",
  first_name: "First name",
  last_name: "Last name",
  full_name: "Full name (split)",
  title: "Title",
  phone: "Phone",
  linkedin_url: "LinkedIn URL",
  source: "Source",
  status: "Status",
  tags: "Tags (; or , separated)",
  company_name: "Company name",
  company_domain: "Company domain",
  website: "Company website",
};

export function ImportWizard({ orgId }: { orgId: string }) {
  const [file, setFile] = useState<{ name: string; content: string } | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, LeadField | "">>({});
  const [policy, setPolicy] = useState<"skip" | "update">("skip");
  const [keepUnmapped, setKeepUnmapped] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  async function choose(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    setError(null);
    setPreview(null);
    setResult(null);
    if (!f) return;
    if (f.size > MAX_BYTES) {
      setError("Files must be 5 MB or smaller. Split larger files into several imports.");
      return;
    }
    const content = await f.text();
    setFile({ name: f.name, content });
    setBusy(true);
    const r = await apiRequest<Preview>(`/organizations/${orgId}/lead-imports/preview`, {
      method: "POST",
      body: { filename: f.name, content },
    });
    setBusy(false);
    if (!r.ok) {
      setError(r.message);
      return;
    }
    setPreview(r.data);
    setMapping(Object.fromEntries(Object.entries(r.data.suggested_mapping).map(([h, v]) => [h, v ?? ""])));
  }

  const chosen = Object.values(mapping).filter(Boolean) as LeadField[];
  const duplicates = chosen.filter((f, i) => chosen.indexOf(f) !== i);
  const hasIdentity = chosen.some((f) => ["email", "first_name", "last_name", "full_name"].includes(f));

  async function run() {
    if (!file) return;
    setBusy(true);
    setError(null);
    const r = await apiRequest<ImportResult>(`/organizations/${orgId}/lead-imports`, {
      method: "POST",
      body: {
        filename: file.name,
        content: file.content,
        mapping: Object.fromEntries(Object.entries(mapping).filter(([, v]) => v)),
        duplicate_policy: policy,
        unmapped_as_custom_fields: keepUnmapped,
      },
    });
    setBusy(false);
    if (!r.ok) setError(r.message);
    else setResult(r.data);
  }

  if (result) return <ImportSummary result={result} onAgain={() => { setResult(null); setPreview(null); setFile(null); }} />;

  return (
    <div className="space-y-6">
      {error && <Alert tone="error">{error}</Alert>}

      <Card>
        <CardHeader title="1. Choose a CSV file" description="UTF-8, comma, semicolon, or tab separated. Up to 10,000 rows." />
        <div className="px-5 py-4">
          <label htmlFor="csv-file" className="sr-only">
            CSV file
          </label>
          <input
            id="csv-file"
            type="file"
            accept=".csv,text/csv"
            onChange={choose}
            disabled={busy}
            className="block text-sm text-fg-muted file:mr-3 file:h-9 file:rounded-md file:border file:border-border file:bg-surface-raised file:px-3 file:text-fg hover:file:border-border-strong"
          />
          {busy && !preview && <p className="mt-2 text-xs text-fg-subtle">Reading file…</p>}
        </div>
      </Card>

      {preview && (
        <>
          <Card>
            <CardHeader
              title="2. Map columns"
              description={`${formatNumber(preview.total_rows)} rows found. Columns set to “Ignore” are skipped.`}
            />
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-fg-subtle">
                  <tr className="border-b border-border">
                    <th className="px-5 py-2 font-medium">Column</th>
                    <th className="px-5 py-2 font-medium">Maps to</th>
                    <th className="px-5 py-2 font-medium">Sample values</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {preview.headers.map((h, col) => (
                    <tr key={h}>
                      <td className="px-5 py-2 font-medium">{h}</td>
                      <td className="px-5 py-2">
                        <SelectField
                          label={`Field for column ${h}`}
                          hideLabel
                          value={mapping[h] ?? ""}
                          onChange={(e) => setMapping((m) => ({ ...m, [h]: e.target.value as LeadField | "" }))}
                          className="w-52"
                        >
                          <option value="">Ignore</option>
                          {(Object.keys(FIELD_LABELS) as LeadField[]).map((f) => (
                            <option key={f} value={f}>
                              {FIELD_LABELS[f]}
                            </option>
                          ))}
                        </SelectField>
                      </td>
                      <td className="max-w-80 truncate px-5 py-2 text-fg-muted">
                        {preview.sample_rows.map((r) => r[col]).filter(Boolean).slice(0, 3).join(" · ") || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(duplicates.length > 0 || !hasIdentity) && (
              <div className="px-5 pb-4">
                <Alert tone="error">
                  {!hasIdentity
                    ? "Map at least one of email, first name, last name, or full name."
                    : `Each field can be mapped once: ${[...new Set(duplicates)].map((d) => FIELD_LABELS[d]).join(", ")}.`}
                </Alert>
              </div>
            )}
          </Card>

          <Card>
            <CardHeader title="3. Duplicates and extras" description="Duplicates are matched by email within your organization." />
            <fieldset className="space-y-2 px-5 py-4 text-sm">
              <legend className="sr-only">Duplicate policy</legend>
              <label className="flex items-start gap-2">
                <input type="radio" name="policy" checked={policy === "skip"} onChange={() => setPolicy("skip")} className="mt-1 accent-[var(--color-accent)]" />
                <span>
                  <strong>Skip existing leads</strong>
                  <span className="block text-xs text-fg-muted">Leads that already exist are left untouched.</span>
                </span>
              </label>
              <label className="flex items-start gap-2">
                <input type="radio" name="policy" checked={policy === "update"} onChange={() => setPolicy("update")} className="mt-1 accent-[var(--color-accent)]" />
                <span>
                  <strong>Update existing leads</strong>
                  <span className="block text-xs text-fg-muted">Fill in values from the file. Blank cells never erase existing data.</span>
                </span>
              </label>
              <label className="flex items-center gap-2 pt-2">
                <input type="checkbox" checked={keepUnmapped} onChange={(e) => setKeepUnmapped(e.target.checked)} className="accent-[var(--color-accent)]" />
                Keep ignored columns as custom fields
              </label>
            </fieldset>
          </Card>

          <Button onClick={run} loading={busy} disabled={duplicates.length > 0 || !hasIdentity}>
            Import {formatNumber(preview.total_rows)} rows
          </Button>
        </>
      )}
    </div>
  );
}

function ImportSummary({ result, onAgain }: { result: ImportResult; onAgain: () => void }) {
  const stats = [
    ["Created", result.created_count],
    ["Updated", result.updated_count],
    ["Skipped", result.skipped_count],
    ["Errors", result.error_count],
  ] as const;
  return (
    <div className="space-y-6">
      {result.replayed && (
        <Alert tone="info">This exact file was already imported with these settings, so nothing changed. Showing the original result.</Alert>
      )}
      <Card>
        <CardHeader title={`Imported ${result.filename}`} description={`${formatNumber(result.total_rows)} rows processed`} />
        <dl className="grid grid-cols-2 gap-4 px-5 py-4 sm:grid-cols-4">
          {stats.map(([label, n]) => (
            <div key={label}>
              <dt className="text-xs text-fg-subtle">{label}</dt>
              <dd className={`text-2xl font-semibold tabular-nums ${label === "Errors" && n > 0 ? "text-danger" : ""}`}>{n}</dd>
            </div>
          ))}
        </dl>
        {result.errors.length > 0 && (
          <div className="border-t border-border">
            <table className="w-full text-sm">
              <caption className="px-5 pt-3 text-left text-xs text-fg-subtle">
                Rows that were not imported{result.error_count > result.errors.length && ` (first ${result.errors.length} shown)`}
              </caption>
              <tbody className="divide-y divide-border">
                {result.errors.map((e) => (
                  <tr key={String(e.row)}>
                    <td className="w-20 px-5 py-2 text-fg-subtle">Row {String(e.row)}</td>
                    <td className="px-5 py-2">{String(e.error)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <div className="flex gap-2">
        <Link
          href={`/leads?import_id=${result.id}`}
          className="inline-flex h-9 items-center rounded-md bg-accent px-4 text-sm font-medium text-accent-fg hover:bg-accent-strong"
        >
          View imported leads
        </Link>
        <Button variant="secondary" onClick={onAgain}>
          Import another file
        </Button>
      </div>
    </div>
  );
}
