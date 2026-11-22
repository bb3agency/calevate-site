"use client";

import type { ReactNode } from "react";
import Link from "next/link";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { ApplyToJobs, appliedSentence, useJobPicks } from "@/components/leadFields/ApplyToJobs";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { useAdminLeadFields, useAdminReplaceLeadFields, type LeadFieldsJob } from "@/lib/api/leadFields";
import { businessTypeOption, useBusinessTypes, type BusinessType } from "@/lib/businessTypes";

/**
 * After an operator moves a client to another business type: the offer to put the new type's
 * standard details onto its campaigns and lines too (D-1029). Never done silently — a client
 * may be collecting into the lists it has on purpose — so the operator ticks which ones. Those
 * nobody customised (empty, or exactly a set the platform offered, such as the old type's)
 * start ticked. Answers already captured stay readable under their old names.
 *
 * A new campaign or line already starts with the new type's set, since the type decides the
 * business's starting set. A type with no standard set ("Something else") has nothing to
 * offer; its lists are changed by hand on Lead details.
 */
export function BusinessTypeMoved({
  tenantId,
  vertical,
}: {
  tenantId: string;
  vertical: BusinessType;
}) {
  const option = businessTypeOption(useBusinessTypes().data, vertical);
  const fields = useAdminLeadFields(tenantId);
  const leadDetails = `/admin/tenants/${tenantId}/lead-details`;

  if (!option) return null;
  const reviewLink = (
    <Link href={leadDetails} className={TEXT_ACTION}>
      Review on Lead details
    </Link>
  );
  if (!option.has_standard_set) {
    return (
      <p className="mt-2">
        Its campaigns and lines keep the lists they have. This business type has no standard set,
        so change them by hand on{" "}
        <Link href={leadDetails} className="font-medium text-brand-strong hover:underline">
          Lead details
        </Link>
        .
      </p>
    );
  }
  if (fields.isPending) return <Skeleton rows={2} label="Loading its campaigns and lines" />;
  if (fields.isError) return <ProblemNotice error={fields.error} onRetry={() => void fields.refetch()} />;
  const label = option.label.toLowerCase();
  if (fields.data.jobs.length === 0) {
    return <p className="mt-2">No campaigns or lines yet. New ones start with the {label} details.</p>;
  }
  return (
    <MoveJobs
      tenantId={tenantId}
      vertical={vertical}
      label={label}
      jobs={fields.data.jobs}
      reviewLink={reviewLink}
    />
  );
}

function MoveJobs({
  tenantId,
  vertical,
  label,
  jobs,
  reviewLink,
}: {
  tenantId: string;
  vertical: BusinessType;
  label: string;
  jobs: LeadFieldsJob[];
  reviewLink: ReactNode;
}) {
  const replace = useAdminReplaceLeadFields(tenantId);
  const feedback = useActionFeedback(replace, { errorDisplay: "inline" });
  const picks = useJobPicks(jobs);
  if (replace.data) {
    return (
      <p role="status" className="mt-2">
        {appliedSentence(replace.data)}
      </p>
    );
  }
  return (
    <div className="mt-2 space-y-3">
      <p>
        New campaigns and lines start with the {label} details. Use them on these too? Answers
        already captured keep their old names.
      </p>
      <ApplyToJobs jobs={jobs} picks={picks} disabled={replace.isPending} legend="Use them on" />
      {replace.error && <ProblemNotice error={replace.error} />}
      <div className="flex flex-wrap items-center gap-3">
        <ActionButton
          variant="secondary"
          status={feedback.status}
          pendingLabel="Replacing…"
          disabled={picks.refs.length === 0}
          onClick={() => replace.mutate({ business_type: vertical, jobs: picks.refs })}
        >
          Use the {label} details
        </ActionButton>
        {reviewLink}
      </div>
    </div>
  );
}
