import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { LeadStatusBadge } from "@/components/ui/status-badge";
import { AssessmentCard } from "@/features/intelligence/assessment-card";
import { BriefCard } from "@/features/intelligence/brief-card";
import { CompanyFacts } from "@/features/intelligence/company-facts";
import { EvidenceCard } from "@/features/intelligence/evidence-card";
import { LeadDetails, NoteForm, OpportunityForm, DeleteLeadButton } from "@/features/leads/lead-profile";
import type { Assessment, AssessmentDetail, Brief, CompanyDetail, Evidence, Icp } from "@/lib/intelligence";
import {
  describeActivity,
  formatDate,
  formatDateTime,
  formatMoney,
  leadName,
  memberName,
  type LeadDetail,
} from "@/lib/crm";
import { getMembers, getStages, orgGet } from "@/lib/org-api";
import { hasPermission } from "@/lib/roles";
import { requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Lead" };

export default async function LeadPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { org } = await requireOrg();
  const orgId = org.organization_id;
  const leadPath = `/leads/${encodeURIComponent(id)}`;
  const [lead, members, stages, icp, evidence, assessments, brief] = await Promise.all([
    orgGet<LeadDetail>(orgId, leadPath),
    getMembers(orgId),
    getStages(orgId),
    orgGet<Icp | null>(orgId, "/icp"),
    orgGet<Evidence[]>(orgId, `${leadPath}/evidence`),
    orgGet<Assessment[]>(orgId, `${leadPath}/assessments`),
    orgGet<Brief>(orgId, `${leadPath}/briefs/latest`),
  ]);
  if (!lead.ok) {
    if (lead.status === 404 || lead.status === 422) notFound();
    return <Alert tone="error">Could not load this lead: {lead.message}</Alert>;
  }
  const l = lead.data;
  const stageList = stages.ok ? stages.data : [];
  const stageName = (sid: string) => stageList.find((s) => s.id === sid)?.name ?? "Unknown stage";
  const can = (p: string) => hasPermission(org.permissions, p);

  const latestId = assessments.ok ? assessments.data[0]?.id : undefined;
  const [latest, company] = await Promise.all([
    latestId ? orgGet<AssessmentDetail>(orgId, `/assessments/${latestId}`) : null,
    l.company ? orgGet<CompanyDetail>(orgId, `/companies/${l.company.id}`) : null,
  ]);
  // Citations show these numbers, and the evidence list below shows the same ones.
  const evidenceList = evidence.ok ? evidence.data : [];
  const evidenceNumbers = new Map(evidenceList.map((e, i) => [e.id, evidenceList.length - i]));
  const intelligenceError = [
    !icp.ok && icp.message,
    !evidence.ok && evidence.message,
    !assessments.ok && assessments.message,
    latest && !latest.ok && latest.message,
    !brief.ok && brief.status !== 404 && brief.message,
  ].find(Boolean);

  return (
    <>
      <p className="mb-2 text-sm">
        <Link href="/leads" className="text-fg-muted hover:text-fg">
          ← Leads
        </Link>
      </p>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex flex-wrap items-center gap-3 text-xl font-semibold tracking-tight">
            {leadName(l)} <LeadStatusBadge status={l.status} />
          </h1>
          <p className="mt-1 text-sm text-fg-muted">
            {[l.title, l.company?.name].filter(Boolean).join(" at ") || "No title or company yet"}
          </p>
        </div>
        {can("leads:delete") && <DeleteLeadButton orgId={orgId} leadId={l.id} />}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <LeadDetails orgId={orgId} lead={l} members={members} canEdit={can("leads:write")} />

          {intelligenceError && <Alert tone="error">Some research data could not be loaded: {intelligenceError}</Alert>}
          <AssessmentCard
            orgId={orgId}
            leadId={l.id}
            assessment={latest?.ok ? latest.data : null}
            evidenceNumbers={evidenceNumbers}
            hasIcp={icp.ok && icp.data !== null}
            canRun={can("assessments:run")}
            canReview={can("intelligence:review")}
          />
          <BriefCard
            orgId={orgId}
            leadId={l.id}
            initial={brief.ok ? brief.data : null}
            evidenceNumbers={evidenceNumbers}
            canRequest={can("research:write")}
          />
          <EvidenceCard
            orgId={orgId}
            leadId={l.id}
            evidence={evidenceList}
            evidenceNumbers={evidenceNumbers}
            companyDomain={company?.ok ? company.data.domain : null}
            canWrite={can("research:write")}
            canReview={can("intelligence:review")}
          />

          <Card>
            <CardHeader title="Timeline" description="Every change to this lead, newest first" />
            {can("leads:write") && (
              <div className="border-b border-border px-5 py-4">
                <NoteForm orgId={orgId} leadId={l.id} />
              </div>
            )}
            <ol className="divide-y divide-border">
              {l.activities.map((a) => {
                const { title, detail } = describeActivity(a, members);
                return (
                  <li key={a.id} className="px-5 py-3 text-sm">
                    <div className="flex flex-wrap justify-between gap-2">
                      <span className="font-medium">{title}</span>
                      <span className="text-xs text-fg-subtle">
                        {memberName(members, a.actor_user_id)} ·{" "}
                        <time dateTime={a.created_at}>{formatDateTime(a.created_at)}</time>
                      </span>
                    </div>
                    {detail && (
                      <p className={a.type === "note" ? "mt-1 whitespace-pre-wrap text-fg" : "mt-0.5 text-xs text-fg-muted"}>
                        {detail}
                      </p>
                    )}
                  </li>
                );
              })}
            </ol>
          </Card>
        </div>

        <div className="space-y-6">
          {company?.ok && <CompanyFacts key={company.data.id} orgId={orgId} company={company.data} canEdit={can("leads:write")} />}
          <Card>
            <CardHeader title="Opportunities" />
            {l.opportunities.length === 0 ? (
              <EmptyState title="No opportunities" body="Create one when this lead shows buying intent." />
            ) : (
              <ul className="divide-y divide-border">
                {l.opportunities.map((o) => (
                  <li key={o.id} className="px-5 py-3 text-sm">
                    <Link href={`/pipeline?highlight=${o.id}`} className="font-medium hover:text-accent">
                      {o.name}
                    </Link>
                    <p className="text-xs text-fg-subtle">
                      {stageName(o.stage_id)}
                      {o.amount != null && ` · ${formatMoney(o.amount, o.currency)}`}
                      {o.expected_close_date && ` · closes ${formatDate(o.expected_close_date)}`}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            {hasPermission(org.permissions, "pipeline:write") && stageList.length > 0 && (
              <div className="border-t border-border px-5 py-4">
                <OpportunityForm
                  orgId={orgId}
                  leadId={l.id}
                  defaultName={l.company?.name ?? leadName(l)}
                  stages={stageList.filter((s) => s.kind === "open")}
                />
              </div>
            )}
          </Card>

          <Card>
            <CardHeader title="Source" />
            <dl className="space-y-3 px-5 py-4 text-sm">
              <div>
                <dt className="text-xs text-fg-subtle">Origin</dt>
                <dd>
                  {l.source ?? "—"}
                  {l.import_id && (
                    <>
                      {" · "}
                      <Link href={`/leads?import_id=${l.import_id}`} className="text-accent hover:underline">
                        view import
                      </Link>
                    </>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-fg-subtle">Added</dt>
                <dd>{formatDateTime(l.created_at)}</dd>
              </div>
              <div>
                <dt className="text-xs text-fg-subtle">Last updated</dt>
                <dd>{formatDateTime(l.updated_at)}</dd>
              </div>
            </dl>
          </Card>
        </div>
      </div>
    </>
  );
}
