"use client";

import { ChecklistRows, type ChecklistRow } from "@/components/console/checklist";
import { holdRule } from "@/lib/api/holds";

/**
 * What is holding this account, at the top of its own page: one row per hold, with its
 * state and the screen that clears it. What each hold blocks sits behind the row's ⓘ.
 *
 * `TenantSummary.holds` is `read_tenant_holds`, the blockers themselves, so this says the
 * same thing as the work list and as the client's refusal. It is here because the panels
 * below all read as "nearly ready", and a refused account should not have to be inferred
 * from a screen full of green.
 *
 * Renders nothing when nothing holds them. A rule this build cannot name is still shown,
 * as itself, routed to the account: an unrecognised hold is still a hold.
 */
export function HoldsBanner({ tenantId, holds }: { tenantId: string; holds: string[] }) {
  if (holds.length === 0) return null;
  const rows: ChecklistRow[] = holds.map((rule) => {
    const copy = holdRule(rule);
    if (!copy) {
      return {
        id: rule,
        label: rule,
        status: "blocked",
        statusText: "Held",
        info: "No description for this hold in this build. The check that set it has one.",
      };
    }
    return {
      id: rule,
      label: copy.item,
      status: copy.rowStatus,
      statusText: copy.status,
      info: (
        <>
          <p>{copy.label}.</p>
          <p>Blocks: {copy.blocks}</p>
          <p>{copy.remedy}</p>
        </>
      ),
      link: { href: copy.screen(tenantId), label: copy.action },
    };
  });
  return (
    <ChecklistRows
      heading={holds.length === 1 ? "Waiting on us" : `Waiting on us: ${holds.length} holds`}
      headingLevel={2}
      tone="warn"
      summary="Inbound answering is unaffected."
      rows={rows}
    />
  );
}
