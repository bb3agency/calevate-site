"use client";

import { use, useMemo, useState } from "react";

import { useAdminAccess } from "@/app/admin/access";
import type { JobNotesSource } from "@/app/c/[slug]/campaigns/CampaignNotes";
import { campaignStatusWord } from "@/app/c/[slug]/campaigns/campaignStatus";
import { useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import { ApplyToJobs, appliedSentence, useJobPicks } from "@/components/leadFields/ApplyToJobs";
import { LeadDetailsView } from "@/components/leadFields/LeadDetailsView";
import { FIELD, FIELD_LABEL, ProblemNotice, SECONDARY_BUTTON, Skeleton } from "@/components/ui";
import {
  businessTypeLabel,
  businessTypeOption,
  useBusinessTypes,
  type BusinessType,
  type BusinessTypes,
} from "@/lib/businessTypes";
import {
  useAdminDraftLeadFields,
  useAdminFetchJobNotes,
  useAdminJobNotes,
  useAdminLeadFields,
  useAdminNameCoreDetails,
  useAdminReplaceLeadFields,
  useAdminSaveJobNotes,
  type LeadFields,
  type LeadFieldsJob,
} from "@/lib/api/leadFields";
import { useAdminLeadSuggestions } from "@/lib/api/leadSuggestions";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { resetIfSettled } from "@/app/admin/resetIfSettled";
import { examplesFor } from "@/lib/verticalExamples";

/**
 * One client's lead details, for an operator (founder decision 15; per campaign and line since
 * D-1029): the same screen the client sees, editing each job's list through the operator's
 * twins of the job notes routes, plus the one operator tool, a business type's standard set
 * onto the ticked campaigns and lines, which is how an account set up on the wrong type is
 * moved. Answers already captured stay readable under their old names.
 */
export default function TenantLeadDetailsPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const fields = useAdminLeadFields(tenantId);
  const businessTypes = useBusinessTypes();
  const write = useAdminAccess("admin:tenants", "change a client's lead details");
  const draft = useAdminDraftLeadFields(tenantId);
  const replace = useAdminReplaceLeadFields(tenantId);
  const nameCore = useAdminNameCoreDetails(tenantId);
  useActionFeedback(nameCore, { errorDisplay: "inline" });
  // Inline: `LeadDetailsView` draws each write's refusal beside its own button.
  useActionFeedback(draft, { errorDisplay: "inline" });
  const replaceFeedback = useActionFeedback(replace, { errorDisplay: "inline" });
  const jobs = fields.data?.jobs;
  // The type's own example rows: an operator has no client copy to read.
  const examples = useMemo(
    () => examplesFor(businessTypeOption(businessTypes.data, fields.data?.business_type ?? null)),
    [businessTypes.data, fields.data?.business_type],
  );
  const source = useMemo((): JobNotesSource => {
    const known = jobs ?? [];
    return {
      audience: "operator",
      useNotes: (kind, jobId) => useAdminJobNotes(tenantId, kind, jobId),
      useSave: (kind, jobId) => useAdminSaveJobNotes(tenantId, kind, jobId),
      useFetch: (kind) => useAdminFetchJobNotes(tenantId, kind),
      // The list this screen already read: no second request for the import menu.
      useOthers: (kind, jobId) => ({
        loading: false,
        failed: false,
        items: known
          .filter((job) => job.kind === kind && job.id !== jobId)
          .map((job) => ({
            id: job.id,
            label: job.name,
            hint: job.kind === "campaign" ? campaignStatusWord(job.status) : job.live ? "Live" : "Draft",
          })),
      }),
      useSuggestions: (kind, jobId) => useAdminLeadSuggestions(tenantId, kind, jobId),
      useAlertsHref: () => null,
      useExamples: () => examples,
    };
  }, [tenantId, jobs, examples]);

  useCopilotSurface({
    route: "/admin/tenants/{id}/lead-details",
    title: "Lead details",
    realm: "admin",
    fields: [],
    facts: fields.data
      ? [
          { key: "tenant_id", label: "Tenant id", value: tenantId },
          { key: "business_type", label: "Business type", value: fields.data.business_type_label },
          {
            key: "starting_set",
            label: "What a new campaign or line starts with (names only)",
            value: fields.data.starting_fields.map((f) => f.label).join(", ") || "only the core",
          },
          {
            key: "jobs",
            label: "What each campaign and line notes (names only)",
            value:
              fields.data.jobs
                .map((job) => `${job.name}: ${job.fields.map((f) => f.label).join(", ") || "only the core"}`)
                .join("; ") || "no campaigns or lines",
          },
          { key: "draft", label: "AI draft", value: fields.data.draft?.status ?? "none" },
        ]
      : [{ key: "state", label: "This client", value: fields.error ? "could not be read" : "still loading" }],
    apply: noFill,
  });

  return (
    <div className="space-y-10">
      <PageHeader
        title="Lead details"
        description="What every call of this client writes down, one list per campaign and line. Nothing already captured is rewritten."
      />
      {fields.isPending ? (
        <Skeleton rows={8} label="Loading the lead details" />
      ) : fields.isError ? (
        <ProblemNotice error={fields.error} onRetry={() => void fields.refetch()} />
      ) : (
        <>
          <LeadDetailsView
            data={fields.data}
            audience="operator"
            canWrite={write.allowed}
            writeReason={write.reason}
            writes={{ draft, replace, nameCore }}
            source={source}
            links={null}
          />
          {write.allowed && fields.data.jobs.length > 0 && businessTypes.data && (
            <ReplaceWithType
              key={fields.data.jobs.map((job) => job.digest).join()}
              data={fields.data}
              types={businessTypes.data}
              replace={replace}
              status={replaceFeedback.status}
            />
          )}
        </>
      )}
    </div>
  );
}

function ReplaceWithType({
  data,
  types,
  replace,
  status,
}: {
  data: LeadFields;
  types: BusinessTypes;
  replace: ReturnType<typeof useAdminReplaceLeadFields>;
  status: FeedbackStatus;
}) {
  const offered = types.choices.filter((option) => option.has_standard_set);
  const current = offered.find((option) => option.value === data.business_type)?.value;
  const [type, setType] = useState<BusinessType>(current ?? offered[0]?.value ?? "");
  const [confirming, setConfirming] = useState(false);
  const picks = useJobPicks(data.jobs);
  if (offered.length === 0) return null;
  const label = businessTypeLabel(types, type).toLowerCase();
  return (
    <Section
      className="max-w-3xl"
      title="Move campaigns and lines to a standard set"
      description="For an account set up on the wrong business type. Change the type under Business details first."
    >
      <div className="space-y-4">
        <label className="block min-w-0">
          <span className={FIELD_LABEL}>Standard details for</span>
          <select
            className={`${FIELD} w-full sm:w-72`}
            value={type}
            onChange={(event) => {
              const next = offered.find((option) => option.value === event.target.value);
              if (next) setType(next.value);
              resetIfSettled(replace);
            }}
          >
            {offered.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <ApplyToJobs jobs={data.jobs} picks={picks} disabled={replace.isPending} legend="Replace the list on" />
        <button
          type="button"
          className={SECONDARY_BUTTON}
          disabled={replace.isPending || picks.refs.length === 0}
          onClick={() => setConfirming(true)}
        >
          Replace on {picks.refs.length}
        </button>
        {replace.data && !confirming && (
          <p role="status" className="text-body text-ink-muted">
            {appliedSentence(replace.data)}
          </p>
        )}
      </div>
      {confirming && (
        <ConfirmDialog
          title={`Use the ${label} set on ${picks.refs.length === 1 ? "1 campaign or line" : `${picks.refs.length} campaigns and lines`}?`}
          confirmLabel="Replace details"
          pendingLabel="Replacing…"
          status={status}
          successLabel="Replaced"
          error={replace.error}
          onCancel={() => setConfirming(false)}
          onConfirm={() =>
            replace.mutate({ business_type: type, jobs: picks.refs }, { onSuccess: () => setConfirming(false) })
          }
        >
          <p>
            {jobNames(data.jobs, picks.refs.map((ref) => `${ref.kind}:${ref.id}`))} will write down the
            standard {label} details from the next call. The client is not told; their Lead details
            screen shows the new lists.
          </p>
          <p>Answers already captured stay on their leads and calls, under their old names.</p>
        </ConfirmDialog>
      )}
    </Section>
  );
}

function jobNames(jobs: LeadFieldsJob[], keys: string[]): string {
  const names = jobs.filter((job) => keys.includes(`${job.kind}:${job.id}`)).map((job) => job.name);
  if (names.length <= 3) return names.join(", ");
  return `${names.slice(0, 3).join(", ")} and ${names.length - 3} more`;
}
