"use client";

import Link from "next/link";

import { ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import { useAdminReplaceLeadFields } from "@/lib/api/leadFields";
import { businessTypeLabel, type BusinessType } from "@/lib/businessTypes";

/**
 * After an operator moves a client to another business type: the offer to move its agents'
 * lead details too. Never done silently — a client may have been collecting into the old
 * details on purpose — and never destructive: replacing writes a new version per agent and
 * every answer already captured stays readable under its old name.
 */
export function BusinessTypeMoved({
  tenantId,
  vertical,
}: {
  tenantId: string;
  vertical: BusinessType;
}) {
  const replace = useAdminReplaceLeadFields(tenantId);
  const label = businessTypeLabel(vertical).toLowerCase();
  const leadDetails = `/admin/tenants/${tenantId}/lead-details`;

  if (vertical === "custom") {
    return (
      <p className="mt-2">
        Its agents still write down the old lead details. A business of this type gets its
        details drafted once from its business details, on{" "}
        <Link href={leadDetails} className="font-medium text-brand-strong hover:underline">
          Lead details
        </Link>
        .
      </p>
    );
  }
  if (replace.data) {
    return (
      <p role="status" className="mt-2">
        {replace.data.agents_changed} agent{replace.data.agents_changed === 1 ? " now writes" : "s now write"}{" "}
        down the {label} details. Answers already captured keep their old names.
      </p>
    );
  }
  return (
    <div className="mt-2 space-y-2">
      <p>
        Its agents still write down the old lead details. Replace them with the standard{" "}
        {label} details? Answers already captured stay readable under their old names.
      </p>
      {replace.error && <ProblemNotice error={replace.error} />}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={SECONDARY_BUTTON}
          disabled={replace.isPending}
          onClick={() => replace.mutate({ business_type: vertical, agent_ids: null })}
        >
          {replace.isPending ? "Replacing…" : `Use the ${label} details`}
        </button>
        <Link href={leadDetails} className="text-sm font-medium text-brand-strong hover:underline">
          Review on Lead details
        </Link>
      </div>
    </div>
  );
}
