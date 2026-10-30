"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { apiRequest } from "@/lib/client-api";
import { parseList, parseOptionalInt, WEIGHT_FIELDS, type Icp, type IcpCreate } from "@/lib/intelligence";

const LIST_FIELDS = [
  ["industries", "Target industries", "Comma-separated, e.g. Fintech, B2B SaaS"],
  ["excluded_industries", "Excluded industries", "A match here always means low fit"],
  ["countries", "Target countries", ""],
  ["target_titles", "Target job titles", "Matched as whole words, e.g. VP Sales, Head of Revenue"],
  ["need_keywords", "Business need keywords", "Looked for in research evidence, e.g. lead scoring"],
  ["intent_keywords", "Buying intent keywords", "e.g. request for proposals"],
  ["timing_keywords", "Timing keywords", "e.g. this quarter, contract renewal"],
  ["negative_keywords", "Negative keywords", "e.g. hiring freeze, acquired"],
] as const;

type ListKey = (typeof LIST_FIELDS)[number][0];
type WeightKey = (typeof WEIGHT_FIELDS)[number][0] | "negative";

const DEFAULT_WEIGHTS: Record<WeightKey, number> = {
  icp_fit: 35,
  need: 20,
  intent: 15,
  timing: 10,
  decision_maker: 10,
  data_quality: 10,
  negative: 25,
};

export function IcpForm({ orgId, current }: { orgId: string; current: Icp | null }) {
  const router = useRouter();
  const c = current?.criteria;
  const [lists, setLists] = useState<Record<ListKey, string>>(() => {
    const out = {} as Record<ListKey, string>;
    for (const [key] of LIST_FIELDS) out[key] = (c?.[key] ?? []).join(", ");
    return out;
  });
  const [minEmployees, setMin] = useState(c?.min_employees?.toString() ?? "");
  const [maxEmployees, setMax] = useState(c?.max_employees?.toString() ?? "");
  const [ttl, setTtl] = useState((c?.signal_ttl_days ?? 180).toString());
  const [weights, setWeights] = useState<Record<WeightKey, string>>(() => {
    const out = {} as Record<WeightKey, string>;
    for (const key of Object.keys(DEFAULT_WEIGHTS) as WeightKey[]) {
      out[key] = String(current?.weights?.[key] ?? DEFAULT_WEIGHTS[key]);
    }
    return out;
  });
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaved(null);
    const min = parseOptionalInt(minEmployees);
    const max = parseOptionalInt(maxEmployees);
    const days = parseOptionalInt(ttl);
    if (min === undefined || max === undefined) return setError("Company size must be a whole number.");
    if (min != null && max != null && min > max) return setError("Minimum size cannot be above the maximum.");
    if (days == null || days < 1) return setError("Signal lifetime must be at least 1 day.");
    const parsedWeights = {} as Record<WeightKey, number>;
    for (const key of Object.keys(DEFAULT_WEIGHTS) as WeightKey[]) {
      const n = parseOptionalInt(weights[key]);
      if (n == null || n > 100) return setError("Each weight must be a whole number from 0 to 100.");
      parsedWeights[key] = n;
    }
    if (WEIGHT_FIELDS.every(([key]) => parsedWeights[key] === 0)) {
      return setError("At least one weight other than the negative penalty must be above zero.");
    }
    const criteria = { min_employees: min, max_employees: max, signal_ttl_days: days } as IcpCreate["criteria"];
    for (const [key] of LIST_FIELDS) criteria[key] = parseList(lists[key]);

    setBusy(true);
    const r = await apiRequest<Icp>(`/organizations/${orgId}/icp`, {
      method: "POST",
      body: { criteria, weights: parsedWeights },
    });
    setBusy(false);
    if (!r.ok) return setError(r.message);
    setSaved(r.data.version);
    router.refresh();
  };

  return (
    <form onSubmit={submit} className="space-y-6" noValidate>
      {error && <Alert tone="error">{error}</Alert>}
      {saved !== null && <Alert tone="success">Saved as version {saved}. New assessments will use it.</Alert>}

      <div className="grid gap-4 sm:grid-cols-2">
        {LIST_FIELDS.map(([key, label, hint]) => (
          <TextField
            key={key}
            label={label}
            hint={hint || undefined}
            value={lists[key]}
            onChange={(e) => setLists((l) => ({ ...l, [key]: e.target.value }))}
          />
        ))}
        <TextField label="Minimum employees" inputMode="numeric" value={minEmployees} onChange={(e) => setMin(e.target.value)} />
        <TextField label="Maximum employees" inputMode="numeric" value={maxEmployees} onChange={(e) => setMax(e.target.value)} />
        <TextField
          label="Signal lifetime (days)"
          hint="Research older than this stops counting"
          inputMode="numeric"
          value={ttl}
          onChange={(e) => setTtl(e.target.value)}
        />
      </div>

      <fieldset>
        <legend className="text-sm font-medium">Scoring weights</legend>
        <p className="mt-1 text-xs text-fg-subtle">
          Weights are relative and scaled so the score runs from 0 to 100. Anything you have not configured is left out.
          The negative penalty is points taken off when a negative keyword is found.
        </p>
        <div className="mt-3 grid gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {WEIGHT_FIELDS.map(([key, label]) => (
            <TextField
              key={key}
              label={label}
              inputMode="numeric"
              value={weights[key]}
              onChange={(e) => setWeights((w) => ({ ...w, [key]: e.target.value }))}
            />
          ))}
          <TextField
            label="Negative penalty"
            inputMode="numeric"
            value={weights.negative}
            onChange={(e) => setWeights((w) => ({ ...w, negative: e.target.value }))}
          />
        </div>
      </fieldset>

      <Button type="submit" loading={busy}>
        Save new version
      </Button>
    </form>
  );
}
