"use client";

import Link from "next/link";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { ProblemNotice } from "@/components/ui";
import { useAdminReplaceLeadFields, type ReplaceOut } from "@/lib/api/leadFields";
import { businessTypeLabel, type BusinessType } from "@/lib/businessTypes";

/**
 * After an operator moves a client to another business type: the offer to move its agents'
 * lead details too. Never done silently — a client may have been collecting into the
 * details it has on purpose — and never destructive: replacing writes a new version per
 * agent and every answer already captured stays readable under its old name.
 *
 * Changing the type rewrites no agent, so the copy says the agents KEEP what they have
 * rather than that they still collect "the old details": an account with no agents, or one
 * whose agents already use this type's set, has nothing old to keep. "Something else" has
 * no standard set to offer, and its one AI draft is no way out either: it is made at most
 * once per business and lands only on agents with no business details of their own
 * (`agents/lead_fields.review_draft`, `only_empty=True`).
 */
export function BusinessTypeMoved({
  tenantId,
  vertical,
}: {
  tenantId: string;
  vertical: BusinessType;
}) {
  const replace = useAdminReplaceLeadFields(tenantId);
  const replaceFeedback = useActionFeedback(replace, { errorDisplay: "inline" });
  const label = businessTypeLabel(vertical).toLowerCase();
  const leadDetails = `/admin/tenants/${tenantId}/lead-details`;

  if (vertical === "custom") {
    return (
      <p className="mt-2">
        Its agents keep the lead details they have now. This business type has no standard
        set, so change them by hand on{" "}
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
        {replacedSentence(replace.data, label)}
      </p>
    );
  }
  return (
    <div className="mt-2 space-y-2">
      <p>
        Its agents keep the lead details they have now. Replace them with the standard{" "}
        {label} details? Answers already captured stay readable under their old names.
      </p>
      {replace.error && <ProblemNotice error={replace.error} />}
      <div className="flex flex-wrap items-center gap-3">
        <ActionButton
          variant="secondary"
          status={replaceFeedback.status}
          pendingLabel="Replacing…"
          onClick={() => replace.mutate({ business_type: vertical, agent_ids: null })}
        >
          Use the {label} details
        </ActionButton>
        <Link href={leadDetails} className={TEXT_ACTION}>
          Review on Lead details
        </Link>
      </div>
    </div>
  );
}

/** What the replace did, from the counts the server returned — never "0 agents now write". */
export function replacedSentence(result: ReplaceOut, label: string): string {
  const { agents_changed: changed, agents_unchanged: unchanged } = result;
  if (changed === 0 && unchanged === 0) {
    return `This account has no agents yet. A new agent starts with the ${label} details.`;
  }
  if (changed === 0) {
    return `Every agent already writes down the ${label} details. Nothing changed.`;
  }
  const verb = changed === 1 ? " now writes" : "s now write";
  return `${changed} agent${verb} down the ${label} details. Answers already captured keep their old names.`;
}
